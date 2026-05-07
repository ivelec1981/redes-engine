# -*- coding: utf-8 -*-
"""
redes_engine.io.gis_importer
=============================

Importador de redes desde formatos GIS estándar:
    - GeoJSON (stdlib, siempre disponible)
    - GeoPackage (.gpkg) — requiere fiona o pyogrio
    - Shapefile (.shp)   — requiere fiona o pyogrio

Estrategia
----------
1. Cada layer GIS aporta una "vista" de la red (postes, tramos, trafos).
2. El importador hace snap de los extremos de líneas a los postes
   más cercanos (con tolerancia configurable).
3. Los buses sin coincidencia explícita se generan automáticamente
   con un ID virtual.
4. El campo de mapeo (FieldMapping) es totalmente configurable para
   adaptarse a las convenciones reales (EEQ, CNEL, EEASA, CENTROSUR).

Layers esperados (nombres flexibles)
------------------------------------
    - postes_mt / postes / poles      → buses MT
    - postes_bt                       → buses BT
    - tramos_mt / lineas_mt / red_mt  → branches LINE_AEREA_MT
    - tramos_bt / lineas_bt / red_bt  → branches LINE_AEREA_BT
    - transformadores / trafos        → branches TRANSFORMER (con bus virtual BT)
    - cargas / loads / medidores      → assets LOAD_RESIDENCIAL
    - ev_chargers / cargadores_ve     → assets EV_*
    - solar_pv / paneles              → assets SOLAR_PV_*
    - bess / almacenamiento           → assets BESS_*
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..core.graph import (
    Asset,
    AssetType,
    Branch,
    BranchType,
    Bus,
    BusType,
    VoltageLevel,
)
from ..core.network import Network

# =============================================================================
# Detección de librerías GIS opcionales
# =============================================================================
try:
    import fiona  # type: ignore
    FIONA_AVAILABLE = True
except ImportError:
    FIONA_AVAILABLE = False

try:
    import pyogrio  # type: ignore
    PYOGRIO_AVAILABLE = True
except ImportError:
    PYOGRIO_AVAILABLE = False

try:
    from shapely.geometry import shape as shapely_shape  # type: ignore
    SHAPELY_AVAILABLE = True
except ImportError:
    SHAPELY_AVAILABLE = False


# =============================================================================
# Field Mapping — campos GIS reales del Ecuador
# =============================================================================
@dataclass
class FieldMapping:
    """
    Mapeo configurable de nombres de campos GIS a atributos del modelo.

    Lista de candidatos por campo (case-insensitive). El importador
    prueba cada uno hasta encontrar una coincidencia.
    """
    # ── Bus / poste / pozo ────────────────────────────────────────────
    bus_id: List[str] = field(default_factory=lambda: [
        "id", "ID", "NUM_SEQ", "NUMERO", "NUM_POSTE", "NOMBRE",
        "BUS", "NODE", "OBJECTID", "FID",
    ])
    bus_voltage_kv: List[str] = field(default_factory=lambda: [
        "voltage_kv", "VOLTAJE", "TENSION", "KV", "TENSION_KV",
    ])
    bus_zone: List[str] = field(default_factory=lambda: [
        "zone", "ALIMENTADOR", "CIRCUITO", "FEEDER", "ZONA",
    ])
    bus_elevation: List[str] = field(default_factory=lambda: [
        "elevation_m", "ALTURA", "COTA", "ELEV",
    ])

    # ── Branch / tramo / línea ────────────────────────────────────────
    branch_id: List[str] = field(default_factory=lambda: [
        "id", "ID", "NUM_SEQ", "NUM_TRAMO", "NOMBRE", "OBJECTID", "FID",
    ])
    branch_bus_from: List[str] = field(default_factory=lambda: [
        "bus_from", "NODO_I", "FROM_BUS", "BUS_I", "DESDE", "ORIGEN",
    ])
    branch_bus_to: List[str] = field(default_factory=lambda: [
        "bus_to", "NODO_J", "TO_BUS", "BUS_J", "HASTA", "DESTINO",
    ])
    branch_length_m: List[str] = field(default_factory=lambda: [
        "length_m", "LONGITUD", "LONG", "DISTANCIA",
    ])
    branch_conductor: List[str] = field(default_factory=lambda: [
        "conductor_type", "CONDUCTOR", "CABLE", "TIPO_COND", "TIPO_CABLE",
    ])
    branch_rated_a: List[str] = field(default_factory=lambda: [
        "rated_a", "AMPACIDAD", "AMPS", "AMP_NOM",
    ])
    branch_r_ohm: List[str] = field(default_factory=lambda: [
        "r_ohm", "RESISTENCIA", "R", "R_TOTAL",
    ])
    branch_x_ohm: List[str] = field(default_factory=lambda: [
        "x_ohm", "REACTANCIA", "X", "X_TOTAL",
    ])

    # ── Transformador ─────────────────────────────────────────────────
    trafo_kva: List[str] = field(default_factory=lambda: [
        "kva", "POT_KVA", "POTENCIA", "POTENCIA_KVA", "KVA_NOM",
    ])
    trafo_kv_primary: List[str] = field(default_factory=lambda: [
        "kv_primary", "KV_PRIM", "PRIMARIO_KV", "VOLT_PRIM",
    ])
    trafo_kv_secondary: List[str] = field(default_factory=lambda: [
        "kv_secondary", "KV_SEC", "SECUNDARIO_KV", "VOLT_SEC",
    ])
    trafo_impedance: List[str] = field(default_factory=lambda: [
        "impedance_pu", "IMPEDANCIA", "Z_PU",
    ])
    trafo_connection: List[str] = field(default_factory=lambda: [
        "connection", "CONEXION", "CONFIG",
    ])

    # ── Asset / carga / generación ────────────────────────────────────
    asset_id: List[str] = field(default_factory=lambda: [
        "id", "ID", "NOMBRE", "OBJECTID", "FID",
    ])
    asset_bus_id: List[str] = field(default_factory=lambda: [
        "bus_id", "POSTE", "NODO", "BUS", "MEDIDOR",
    ])
    asset_rated_kw: List[str] = field(default_factory=lambda: [
        "rated_kw", "KW", "POT_KW", "DEMANDA_KW", "POTENCIA_KW",
    ])
    asset_rated_kvar: List[str] = field(default_factory=lambda: [
        "rated_kvar", "KVAR", "REACTIVA",
    ])
    asset_capacity_kwh: List[str] = field(default_factory=lambda: [
        "capacity_kwh", "ENERGIA_KWH", "KWH",
    ])

    def first_match(self, attrs: Dict[str, Any], candidates: List[str]) -> Optional[Any]:
        """Busca el primer campo que exista en attrs (case-insensitive)."""
        # Crear un mapa lower-case
        lower_attrs = {k.lower(): v for k, v in attrs.items()}
        for cand in candidates:
            v = lower_attrs.get(cand.lower())
            if v is not None and v != "":
                return v
        return None


# =============================================================================
# Diagnóstico de importación
# =============================================================================
@dataclass
class ImportReport:
    """Reporte detallado del proceso de importación."""
    buses_imported: int = 0
    buses_auto_created: int = 0
    branches_imported: int = 0
    transformers_imported: int = 0
    assets_imported: int = 0
    snap_matches: int = 0
    snap_failures: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "═" * 60,
            "  REPORTE DE IMPORTACIÓN GIS",
            "═" * 60,
            f"  Buses importados        : {self.buses_imported}",
            f"  Buses auto-creados      : {self.buses_auto_created} (snap virtual)",
            f"  Líneas (branches)       : {self.branches_imported}",
            f"  Transformadores         : {self.transformers_imported}",
            f"  Assets (cargas/etc.)    : {self.assets_imported}",
            f"  ────────────────────────────────────────────",
            f"  Snap matches            : {self.snap_matches}",
            f"  Snap failures           : {self.snap_failures}",
        ]
        if self.warnings:
            lines.append(f"  ⚠ Advertencias          : {len(self.warnings)}")
            for w in self.warnings[:5]:
                lines.append(f"     • {w}")
            if len(self.warnings) > 5:
                lines.append(f"     ... y {len(self.warnings)-5} más")
        if self.errors:
            lines.append(f"  ❌ Errores              : {len(self.errors)}")
            for e in self.errors[:5]:
                lines.append(f"     • {e}")
        lines.append("═" * 60)
        return "\n".join(lines)


# =============================================================================
# IMPORTADOR PRINCIPAL
# =============================================================================
class GISImporter:
    """
    Importador de redes desde GeoJSON / GeoPackage / Shapefile.

    Construye un Network listo para resolver con OpenDSSSolver.
    """

    def __init__(
        self,
        mapping: Optional[FieldMapping] = None,
        snap_tolerance_m: float = 5.0,
        default_voltage_mt_kv: float = 22.8,
        default_voltage_bt_kv: float = 0.220,
    ):
        self.mapping = mapping or FieldMapping()
        self.snap_tolerance_m = snap_tolerance_m
        self.default_voltage_mt = default_voltage_mt_kv
        self.default_voltage_bt = default_voltage_bt_kv

    # =========================================================================
    # ENTRADA PRINCIPAL: GeoJSON
    # =========================================================================
    def from_geojson(
        self,
        layers: Dict[str, str],
        network_name: str = "Imported",
    ) -> Tuple[Network, ImportReport]:
        """
        Construye una Network desde múltiples archivos GeoJSON.

        Parameters
        ----------
        layers : dict
            Diccionario {tipo_capa: ruta_geojson}. Tipos válidos:
                - "postes_mt"      → buses MT
                - "postes_bt"      → buses BT
                - "tramos_mt"      → líneas MT
                - "tramos_bt"      → líneas BT
                - "transformadores"→ trafos
                - "cargas"         → assets LOAD_*
                - "ev_chargers"    → assets EV_*
                - "solar_pv"       → assets PV_*
                - "bess"           → assets BESS_*
        network_name : str

        Returns
        -------
        (Network, ImportReport)
        """
        net = Network(name=network_name)
        report = ImportReport()

        # 1. Importar buses primero
        for layer_type in ("postes_mt", "postes_bt"):
            if layer_type in layers:
                features = self._read_geojson(layers[layer_type], report)
                self._import_buses(net, features, layer_type, report)

        # 2. Importar líneas (snap a buses existentes)
        for layer_type in ("tramos_mt", "tramos_bt"):
            if layer_type in layers:
                features = self._read_geojson(layers[layer_type], report)
                self._import_lines(net, features, layer_type, report)

        # 3. Importar transformadores
        if "transformadores" in layers:
            features = self._read_geojson(layers["transformadores"], report)
            self._import_transformers(net, features, report)

        # 4. Importar assets
        for layer_type, asset_factory in [
            ("cargas", self._make_load_asset),
            ("ev_chargers", self._make_ev_asset),
            ("solar_pv", self._make_pv_asset),
            ("bess", self._make_bess_asset),
        ]:
            if layer_type in layers:
                features = self._read_geojson(layers[layer_type], report)
                self._import_assets(net, features, asset_factory, report)

        return net, report

    # =========================================================================
    # ENTRADA: GeoPackage / Shapefile (requieren fiona o pyogrio)
    # =========================================================================
    def from_geopackage(
        self,
        gpkg_path: str,
        layer_mapping: Dict[str, str],
        network_name: str = "Imported",
    ) -> Tuple[Network, ImportReport]:
        """
        Importa desde un .gpkg con múltiples capas.

        Parameters
        ----------
        gpkg_path : str
            Ruta al archivo GeoPackage.
        layer_mapping : dict
            {nombre_capa_en_gpkg: tipo_logico}, p.ej.:
                {"postes": "postes_mt", "tramos_mt": "tramos_mt", ...}
        """
        if not (FIONA_AVAILABLE or PYOGRIO_AVAILABLE):
            raise RuntimeError(
                "Para leer GeoPackage instale: pip install pyogrio (recomendado) "
                "o pip install fiona"
            )

        layers_features: Dict[str, list] = {}
        for layer_name, logical_type in layer_mapping.items():
            features = self._read_gpkg_layer(gpkg_path, layer_name)
            layers_features[logical_type] = features

        return self._build_from_features(layers_features, network_name)

    def from_shapefiles(
        self,
        files: Dict[str, str],
        network_name: str = "Imported",
    ) -> Tuple[Network, ImportReport]:
        """
        Importa desde varios shapefiles (uno por tipo).

        Parameters
        ----------
        files : dict
            {tipo_logico: ruta_al_shp}
        """
        if not (FIONA_AVAILABLE or PYOGRIO_AVAILABLE):
            raise RuntimeError(
                "Para leer Shapefile instale: pip install pyogrio o pip install fiona"
            )
        layers_features: Dict[str, list] = {}
        for logical_type, shp_path in files.items():
            features = self._read_shp(shp_path)
            layers_features[logical_type] = features
        return self._build_from_features(layers_features, network_name)

    # =========================================================================
    # READERS
    # =========================================================================
    def _read_geojson(self, path: str, report: ImportReport) -> List[dict]:
        """Lee un GeoJSON y devuelve lista de features."""
        if not os.path.exists(path):
            report.errors.append(f"Archivo no encontrado: {path}")
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("type") == "FeatureCollection":
                return data.get("features", [])
            elif data.get("type") == "Feature":
                return [data]
            else:
                report.warnings.append(f"Estructura inesperada en {path}")
                return []
        except (json.JSONDecodeError, OSError) as e:
            report.errors.append(f"Error leyendo {path}: {e}")
            return []

    def _read_gpkg_layer(self, gpkg_path: str, layer_name: str) -> List[dict]:
        """Lee una capa de GeoPackage como features GeoJSON-like."""
        if PYOGRIO_AVAILABLE:
            import pyogrio  # type: ignore
            gdf_dict = pyogrio.read_dataframe(gpkg_path, layer=layer_name)
            features = []
            for idx, row in gdf_dict.iterrows():
                geom = row.geometry
                props = {k: v for k, v in row.items() if k != "geometry"}
                features.append({
                    "type": "Feature",
                    "properties": props,
                    "geometry": _shapely_to_geojson(geom),
                })
            return features
        elif FIONA_AVAILABLE:
            import fiona  # type: ignore
            with fiona.open(gpkg_path, layer=layer_name) as src:
                return [
                    {
                        "type": "Feature",
                        "properties": dict(rec["properties"]),
                        "geometry": dict(rec["geometry"]),
                    }
                    for rec in src
                ]
        return []

    def _read_shp(self, shp_path: str) -> List[dict]:
        """Lee un shapefile como features."""
        if PYOGRIO_AVAILABLE:
            import pyogrio  # type: ignore
            gdf = pyogrio.read_dataframe(shp_path)
            features = []
            for idx, row in gdf.iterrows():
                props = {k: v for k, v in row.items() if k != "geometry"}
                features.append({
                    "type": "Feature",
                    "properties": props,
                    "geometry": _shapely_to_geojson(row.geometry),
                })
            return features
        elif FIONA_AVAILABLE:
            import fiona  # type: ignore
            with fiona.open(shp_path) as src:
                return [
                    {
                        "type": "Feature",
                        "properties": dict(rec["properties"]),
                        "geometry": dict(rec["geometry"]),
                    }
                    for rec in src
                ]
        return []

    # =========================================================================
    # ENTRADA PÚBLICA: features ya parseadas en memoria
    # =========================================================================
    def from_features(
        self, layers_features: Dict[str, list],
        network_name: str = "Imported",
    ) -> Tuple[Network, ImportReport]:
        """
        Importa desde diccionario de features GeoJSON-like ya parseadas.

        Útil cuando los datos vienen de:
            - Capas QGIS (QgsVectorLayer)
            - Bases de datos espaciales (PostGIS)
            - APIs REST que devuelven GeoJSON
            - Tests con datos sintéticos

        Parameters
        ----------
        layers_features : dict
            {tipo_logico: [feature_dict, ...]}
            Cada feature debe tener: type, properties, geometry.
        network_name : str

        Returns
        -------
        (Network, ImportReport)
        """
        return self._build_from_features(layers_features, network_name)

    # =========================================================================
    # PROCESAMIENTO INTERNO
    # =========================================================================
    def _build_from_features(
        self, layers_features: Dict[str, list], network_name: str
    ) -> Tuple[Network, ImportReport]:
        net = Network(name=network_name)
        report = ImportReport()
        for layer_type in ("postes_mt", "postes_bt"):
            if layer_type in layers_features:
                self._import_buses(net, layers_features[layer_type], layer_type, report)
        for layer_type in ("tramos_mt", "tramos_bt"):
            if layer_type in layers_features:
                self._import_lines(net, layers_features[layer_type], layer_type, report)
        if "transformadores" in layers_features:
            self._import_transformers(net, layers_features["transformadores"], report)
        for layer_type, factory in [
            ("cargas", self._make_load_asset),
            ("ev_chargers", self._make_ev_asset),
            ("solar_pv", self._make_pv_asset),
            ("bess", self._make_bess_asset),
        ]:
            if layer_type in layers_features:
                self._import_assets(net, layers_features[layer_type], factory, report)
        return net, report

    def _import_buses(
        self, net: Network, features: List[dict], layer_type: str,
        report: ImportReport,
    ) -> None:
        is_mt = layer_type == "postes_mt"
        default_v = self.default_voltage_mt if is_mt else self.default_voltage_bt
        level = VoltageLevel.MT_22_8KV if is_mt else VoltageLevel.BT_220_127
        bus_type = BusType.POSTE_MT if is_mt else BusType.POSTE_BT

        for feat in features:
            try:
                props = feat.get("properties", {}) or {}
                geom = feat.get("geometry", {}) or {}
                if geom.get("type") != "Point":
                    report.warnings.append(
                        f"Bus con geometría no-Point ignorado en {layer_type}"
                    )
                    continue
                coords = geom.get("coordinates", [0, 0])
                if len(coords) < 2:
                    continue
                bus_id = self._extract_id(props, self.mapping.bus_id, "BUS")
                voltage = self.mapping.first_match(
                    props, self.mapping.bus_voltage_kv) or default_v
                zone = self.mapping.first_match(props, self.mapping.bus_zone)
                elev = self.mapping.first_match(
                    props, self.mapping.bus_elevation) or 0.0

                if bus_id in net.buses:
                    report.warnings.append(f"Bus duplicado ignorado: {bus_id}")
                    continue

                net.add_bus(Bus(
                    id=str(bus_id),
                    geometry=(float(coords[0]), float(coords[1])),
                    voltage_kv=float(voltage),
                    level=level,
                    bus_type=bus_type,
                    elevation_m=float(elev),
                    zone=str(zone) if zone else None,
                ))
                report.buses_imported += 1
            except Exception as e:
                report.errors.append(f"Bus en {layer_type}: {e}")

    def _import_lines(
        self, net: Network, features: List[dict], layer_type: str,
        report: ImportReport,
    ) -> None:
        is_mt = layer_type == "tramos_mt"
        branch_type = (BranchType.LINE_AEREA_MT if is_mt
                       else BranchType.LINE_AEREA_BT)
        level = VoltageLevel.MT_22_8KV if is_mt else VoltageLevel.BT_220_127

        for feat in features:
            try:
                props = feat.get("properties", {}) or {}
                geom = feat.get("geometry", {}) or {}
                if geom.get("type") != "LineString":
                    report.warnings.append(
                        f"Línea con geometría no-LineString ignorada"
                    )
                    continue
                coords = geom.get("coordinates", [])
                if len(coords) < 2:
                    continue

                line_id = self._extract_id(props, self.mapping.branch_id, "L")
                # Extremos
                p1 = (float(coords[0][0]), float(coords[0][1]))
                p2 = (float(coords[-1][0]), float(coords[-1][1]))

                # Buscar buses por nombre primero (si los campos lo dicen)
                explicit_from = self.mapping.first_match(
                    props, self.mapping.branch_bus_from)
                explicit_to = self.mapping.first_match(
                    props, self.mapping.branch_bus_to)

                bus_from = (str(explicit_from) if explicit_from
                            else self._snap_or_create_bus(net, p1, level, report))
                bus_to = (str(explicit_to) if explicit_to
                          else self._snap_or_create_bus(net, p2, level, report))

                if bus_from not in net.buses or bus_to not in net.buses:
                    report.warnings.append(
                        f"Línea {line_id}: bus_from={bus_from} o "
                        f"bus_to={bus_to} no existe — descartada"
                    )
                    continue

                length = (self.mapping.first_match(
                    props, self.mapping.branch_length_m)
                    or _compute_length(coords))
                conductor = self.mapping.first_match(
                    props, self.mapping.branch_conductor)
                rated_a = self.mapping.first_match(
                    props, self.mapping.branch_rated_a) or 0.0
                r_ohm = self.mapping.first_match(
                    props, self.mapping.branch_r_ohm) or 0.0
                x_ohm = self.mapping.first_match(
                    props, self.mapping.branch_x_ohm) or 0.0

                net.add_branch(Branch(
                    id=str(line_id),
                    bus_from=bus_from, bus_to=bus_to,
                    branch_type=branch_type,
                    geometry=[(float(x), float(y)) for x, y in coords],
                    length_m=float(length),
                    r_ohm=float(r_ohm), x_ohm=float(x_ohm),
                    rated_a=float(rated_a),
                    conductor_type=str(conductor) if conductor else None,
                ))
                report.branches_imported += 1
            except Exception as e:
                report.errors.append(f"Línea en {layer_type}: {e}")

    def _import_transformers(
        self, net: Network, features: List[dict], report: ImportReport,
    ) -> None:
        for feat in features:
            try:
                props = feat.get("properties", {}) or {}
                geom = feat.get("geometry", {}) or {}
                if geom.get("type") != "Point":
                    report.warnings.append(
                        "Transformador con geometría no-Point ignorado"
                    )
                    continue
                coords = geom.get("coordinates", [0, 0])
                trafo_id = self._extract_id(props, self.mapping.branch_id, "T")
                kva = self.mapping.first_match(
                    props, self.mapping.trafo_kva) or 75.0
                kv_p = self.mapping.first_match(
                    props, self.mapping.trafo_kv_primary) or self.default_voltage_mt
                kv_s = self.mapping.first_match(
                    props, self.mapping.trafo_kv_secondary) or self.default_voltage_bt
                z_pu = self.mapping.first_match(
                    props, self.mapping.trafo_impedance) or 0.04
                conn = self.mapping.first_match(
                    props, self.mapping.trafo_connection) or "Dyn1"

                # Bus primario: snap al poste MT más cercano
                pt = (float(coords[0]), float(coords[1]))
                bus_p = self._snap_to_existing(net, pt, mt_only=True)
                if bus_p is None:
                    bus_p = self._auto_create_bus(
                        net, pt, VoltageLevel.MT_22_8KV, "TRAFO_PRIM", report
                    )

                # Bus secundario: PRIMERO intentar snap a un poste BT cercano
                bus_s_id = self._snap_to_existing_bt(net, pt)
                if bus_s_id is None:
                    # Si no hay poste BT cercano, crear uno virtual
                    bus_s_id = f"{bus_p}_BT"
                    if bus_s_id not in net.buses:
                        net.add_bus(Bus(
                            id=bus_s_id,
                            geometry=(pt[0], pt[1] + 1.0),
                            voltage_kv=float(kv_s),
                            level=VoltageLevel.BT_220_127,
                            bus_type=BusType.NODO_TRAFO,
                        ))
                        report.buses_auto_created += 1
                else:
                    report.snap_matches += 1

                net.add_branch(Branch(
                    id=str(trafo_id),
                    bus_from=bus_p, bus_to=bus_s_id,
                    branch_type=BranchType.TRANSFORMER,
                    geometry=[(pt[0], pt[1]), (pt[0], pt[1] + 1.0)],
                    length_m=1.0,
                    kva=float(kva),
                    kv_primary=float(kv_p),
                    kv_secondary=float(kv_s),
                    impedance_pu=float(z_pu),
                    connection=str(conn),
                ))
                report.transformers_imported += 1
            except Exception as e:
                report.errors.append(f"Transformador: {e}")

    def _import_assets(
        self, net: Network, features: List[dict],
        factory_fn, report: ImportReport,
    ) -> None:
        for feat in features:
            try:
                props = feat.get("properties", {}) or {}
                geom = feat.get("geometry", {}) or {}
                if geom.get("type") != "Point":
                    continue
                coords = geom.get("coordinates", [0, 0])
                pt = (float(coords[0]), float(coords[1]))

                # bus_id: explícito o snap
                bus_id = self.mapping.first_match(props, self.mapping.asset_bus_id)
                if not bus_id:
                    snapped = self._snap_to_existing(net, pt, bt_preferred=True)
                    if snapped is None:
                        report.snap_failures += 1
                        report.warnings.append(
                            "Asset sin bus cercano — descartado"
                        )
                        continue
                    bus_id = snapped
                else:
                    bus_id = str(bus_id)

                if bus_id not in net.buses:
                    report.warnings.append(
                        f"Asset apunta a bus inexistente {bus_id} — descartado"
                    )
                    continue

                asset = factory_fn(props, bus_id, report)
                if asset is not None:
                    net.add_asset(asset)
                    report.assets_imported += 1
            except Exception as e:
                report.errors.append(f"Asset: {e}")

    # =========================================================================
    # FACTORIES de ASSETS
    # =========================================================================
    def _make_load_asset(self, props: dict, bus_id: str,
                         report: ImportReport) -> Optional[Asset]:
        asset_id = self._extract_id(props, self.mapping.asset_id, "LD")
        kw = self.mapping.first_match(props, self.mapping.asset_rated_kw) or 4.0
        kvar = self.mapping.first_match(
            props, self.mapping.asset_rated_kvar) or 0.0
        return Asset(
            id=str(asset_id), bus_id=bus_id,
            asset_type=AssetType.LOAD_RESIDENCIAL,
            rated_kw=float(kw), rated_kvar=float(kvar),
        )

    def _make_ev_asset(self, props: dict, bus_id: str,
                       report: ImportReport) -> Optional[Asset]:
        asset_id = self._extract_id(props, self.mapping.asset_id, "EV")
        kw = self.mapping.first_match(props, self.mapping.asset_rated_kw) or 7.4
        # Inferir tipo VE por potencia
        if kw < 3:
            atype = AssetType.EV_CHARGER_AC_L1
        elif kw < 25:
            atype = AssetType.EV_CHARGER_AC_L2
        elif kw < 200:
            atype = AssetType.EV_CHARGER_DC_FAST
        else:
            atype = AssetType.EV_CHARGER_DC_ULTRA
        return Asset(
            id=str(asset_id), bus_id=bus_id, asset_type=atype,
            rated_kw=float(kw), controllable=True,
        )

    def _make_pv_asset(self, props: dict, bus_id: str,
                       report: ImportReport) -> Optional[Asset]:
        asset_id = self._extract_id(props, self.mapping.asset_id, "PV")
        kw = self.mapping.first_match(props, self.mapping.asset_rated_kw) or 5.0
        if kw < 50:
            atype = AssetType.SOLAR_PV_RESID
        elif kw < 1000:
            atype = AssetType.SOLAR_PV_COMERCIAL
        else:
            atype = AssetType.SOLAR_PV_UTILITY
        return Asset(
            id=str(asset_id), bus_id=bus_id, asset_type=atype,
            rated_kw=float(kw), capacity_factor=0.18,
        )

    def _make_bess_asset(self, props: dict, bus_id: str,
                         report: ImportReport) -> Optional[Asset]:
        asset_id = self._extract_id(props, self.mapping.asset_id, "BESS")
        kw = self.mapping.first_match(props, self.mapping.asset_rated_kw) or 5.0
        kwh = self.mapping.first_match(
            props, self.mapping.asset_capacity_kwh) or (kw * 2)
        if kw < 10:
            atype = AssetType.BESS_BTM
        elif kw < 500:
            atype = AssetType.BESS_C_AND_I
        else:
            atype = AssetType.BESS_GRID_SCALE
        return Asset(
            id=str(asset_id), bus_id=bus_id, asset_type=atype,
            rated_kw=float(kw), capacity_kwh=float(kwh),
            controllable=True, bidirectional=True,
            soc_initial=0.5,
        )

    # =========================================================================
    # SNAP ESPACIAL
    # =========================================================================
    def _snap_to_existing(
        self, net: Network, point: Tuple[float, float],
        mt_only: bool = False, bt_preferred: bool = False,
    ) -> Optional[str]:
        """Encuentra el bus existente más cercano al punto, dentro de la tolerancia."""
        best_id = None
        best_dist = self.snap_tolerance_m
        for bus in net.buses.values():
            if mt_only and not bus.is_mt():
                continue
            d = math.hypot(bus.geometry[0] - point[0],
                           bus.geometry[1] - point[1])
            if d < best_dist:
                best_dist = d
                best_id = bus.id
        return best_id

    def _snap_to_existing_bt(
        self, net: Network, point: Tuple[float, float],
        tolerance_m: Optional[float] = None,
    ) -> Optional[str]:
        """Snap específico para el secundario del transformador: solo buses BT."""
        tol = tolerance_m if tolerance_m is not None else self.snap_tolerance_m
        best_id = None
        best_dist = tol
        for bus in net.buses.values():
            if not bus.is_bt():
                continue
            d = math.hypot(bus.geometry[0] - point[0],
                           bus.geometry[1] - point[1])
            if d < best_dist:
                best_dist = d
                best_id = bus.id
        return best_id

    def _snap_or_create_bus(
        self, net: Network, point: Tuple[float, float],
        level: VoltageLevel, report: ImportReport,
    ) -> str:
        snapped = self._snap_to_existing(net, point)
        if snapped is not None:
            report.snap_matches += 1
            return snapped
        return self._auto_create_bus(net, point, level, "AUTO", report)

    def _auto_create_bus(
        self, net: Network, point: Tuple[float, float],
        level: VoltageLevel, prefix: str, report: ImportReport,
    ) -> str:
        report.buses_auto_created += 1
        is_mt = level == VoltageLevel.MT_22_8KV
        bus_id = f"{prefix}_{report.buses_auto_created:04d}"
        net.add_bus(Bus(
            id=bus_id, geometry=point,
            voltage_kv=self.default_voltage_mt if is_mt else self.default_voltage_bt,
            level=level,
            bus_type=BusType.POSTE_MT if is_mt else BusType.POSTE_BT,
        ))
        return bus_id

    def _extract_id(self, props: dict, candidates: List[str], prefix: str) -> str:
        v = self.mapping.first_match(props, candidates)
        if v is not None and str(v) != "":
            return str(v)
        # ID auto-generado
        import uuid
        return f"{prefix}_{uuid.uuid4().hex[:8].upper()}"


# =============================================================================
# UTILIDADES
# =============================================================================
def _compute_length(coords: List[List[float]]) -> float:
    """Longitud euclídea de una polilínea (en unidades del SRC)."""
    total = 0.0
    for i in range(len(coords) - 1):
        x1, y1 = coords[i][0], coords[i][1]
        x2, y2 = coords[i + 1][0], coords[i + 1][1]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def _shapely_to_geojson(geom) -> dict:
    """Convierte una geometría shapely a dict GeoJSON."""
    if geom is None:
        return {"type": "Point", "coordinates": [0, 0]}
    return json.loads(json.dumps({
        "type": geom.geom_type,
        "coordinates": _shapely_coords(geom),
    }))


def _shapely_coords(geom):
    """Extrae coordenadas en formato listas."""
    if geom.geom_type == "Point":
        return [geom.x, geom.y]
    if geom.geom_type == "LineString":
        return [[x, y] for x, y in geom.coords]
    if geom.geom_type == "Polygon":
        return [[[x, y] for x, y in ring.coords] for ring in
                ([geom.exterior] + list(geom.interiors))]
    return []
