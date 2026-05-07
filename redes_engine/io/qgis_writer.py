# -*- coding: utf-8 -*-
"""
redes_engine.io.qgis_writer
============================

Escribe los resultados de simulación como capas GeoJSON con atributos
enriquecidos + archivos QML de simbología, listos para arrastrar en QGIS.

Filosofía
---------
    El motor NO depende de QGIS. Solo escribe archivos GeoJSON + QML.
    QGIS los carga aplicando automáticamente la simbología (mismo
    nombre base que el archivo de la capa).

Salida típica (un directorio):
    output/
    ├── postes_resultados.geojson
    ├── postes_resultados.qml          ← QGIS aplica esto automáticamente
    ├── lineas_resultados.geojson
    ├── lineas_resultados.qml
    ├── transformadores_resultados.geojson
    ├── transformadores_resultados.qml
    └── cargar_en_qgis.py              ← script para consola QGIS
"""

import json
import os
from typing import Optional

from ..core.compliance import ComplianceReport
from ..core.network import Network
from ..core.results import ComplianceStatus, PowerFlowResult
from . import qml_templates


# =============================================================================
# WRITER PRINCIPAL
# =============================================================================
class QGISResultsWriter:
    """
    Genera el conjunto de artefactos QGIS desde un Network resuelto.

    Uso típico:
        writer = QGISResultsWriter(net, result, compliance)
        writer.write("output_qgis/")

    Luego en QGIS:
        - Abrir output_qgis/postes_resultados.geojson  → ya viene coloreado
        - Abrir output_qgis/lineas_resultados.geojson  → ya viene graduado
    """

    def __init__(
        self,
        network: Network,
        flow_result: PowerFlowResult,
        compliance_report: Optional[ComplianceReport] = None,
        crs: str = "EPSG:32717",
    ):
        self.net = network
        self.result = flow_result
        self.compliance = compliance_report
        self.crs = crs

    # =========================================================================
    # API principal
    # =========================================================================
    def write(self, output_dir: str) -> dict:
        """
        Genera todos los archivos.

        Returns
        -------
        dict con rutas de los archivos generados.
        """
        os.makedirs(output_dir, exist_ok=True)
        files = {}

        # 1. Buses (postes / pozos)
        files["buses_geojson"] = self._write_buses_geojson(output_dir)
        files["buses_qml"] = self._write_buses_qml(output_dir)

        # 2. Líneas (tramos)
        files["lines_geojson"] = self._write_lines_geojson(output_dir)
        files["lines_qml"] = self._write_lines_qml(output_dir)

        # 3. Transformadores (subset de branches)
        files["trafos_geojson"] = self._write_transformers_geojson(output_dir)
        files["trafos_qml"] = self._write_transformers_qml(output_dir)

        # 4. Loader script para QGIS Python console
        files["loader_script"] = self._write_loader_script(output_dir)

        # 5. README explicativo
        files["readme"] = self._write_readme(output_dir)

        return files

    # =========================================================================
    # GEOJSON: BUSES
    # =========================================================================
    def _write_buses_geojson(self, output_dir: str) -> str:
        """Escribe puntos de buses con resultados como atributos."""
        features = []
        for bus_id, bus in self.net.buses.items():
            v_result = self.result.bus_voltages.get(bus_id)

            props = {
                "id": bus.id,
                "voltage_kv_nominal": bus.voltage_kv,
                "level": bus.level.value,
                "bus_type": bus.bus_type.value,
                "zone": bus.zone or "",
            }

            # Anexar resultados si existen
            if v_result is not None:
                props.update({
                    "v_kv": round(v_result.v_magnitude_kv, 4),
                    "v_pu": round(v_result.v_pu, 4),
                    "v_drop_pct": round(v_result.v_drop_pct, 3),
                    "angle_deg": round(v_result.angle_deg, 2),
                    "compliance": v_result.compliance.value,
                })
            else:
                props.update({
                    "v_kv": None,
                    "v_pu": None,
                    "v_drop_pct": None,
                    "angle_deg": None,
                    "compliance": "unknown",
                })

            features.append({
                "type": "Feature",
                "properties": props,
                "geometry": {
                    "type": "Point",
                    "coordinates": [bus.geometry[0], bus.geometry[1]],
                },
            })

        return self._write_geojson_file(
            output_dir, "postes_resultados.geojson",
            features, name="Postes con resultados",
        )

    def _write_buses_qml(self, output_dir: str) -> str:
        path = os.path.join(output_dir, "postes_resultados.qml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(qml_templates.qml_buses_compliance())
        return path

    # =========================================================================
    # GEOJSON: LÍNEAS
    # =========================================================================
    def _write_lines_geojson(self, output_dir: str) -> str:
        features = []
        for branch_id, branch in self.net.branches.items():
            if not branch.is_line():
                continue
            flow = self.result.branch_flows.get(branch_id)

            props = {
                "id": branch.id,
                "bus_from": branch.bus_from,
                "bus_to": branch.bus_to,
                "branch_type": branch.branch_type.value,
                "length_m": branch.length_m,
                "conductor_type": branch.conductor_type or "",
                "rated_a": branch.rated_a,
            }

            if flow is not None:
                props.update({
                    "p_kw": round(flow.p_kw, 2),
                    "q_kvar": round(flow.q_kvar, 2),
                    "s_kva": round(flow.s_kva, 2),
                    "current_a": round(flow.current_a, 2),
                    "loading_pct": round(flow.loading_pct, 2),
                    "losses_kw": round(flow.losses_kw, 4),
                    "compliance": flow.compliance.value,
                })
            else:
                props.update({
                    "p_kw": None, "q_kvar": None, "s_kva": None,
                    "current_a": None, "loading_pct": 0.0,
                    "losses_kw": None, "compliance": "unknown",
                })

            features.append({
                "type": "Feature",
                "properties": props,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[x, y] for x, y in branch.geometry],
                },
            })

        return self._write_geojson_file(
            output_dir, "lineas_resultados.geojson",
            features, name="Líneas con resultados",
        )

    def _write_lines_qml(self, output_dir: str) -> str:
        path = os.path.join(output_dir, "lineas_resultados.qml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(qml_templates.qml_lines_loading())
        return path

    # =========================================================================
    # GEOJSON: TRANSFORMADORES
    # =========================================================================
    def _write_transformers_geojson(self, output_dir: str) -> str:
        features = []
        for branch in self.net.transformers():
            flow = self.result.branch_flows.get(branch.id)
            # Punto medio del transformador
            x, y = branch.geometry[0]

            props = {
                "id": branch.id,
                "kva": branch.kva,
                "kv_primary": branch.kv_primary,
                "kv_secondary": branch.kv_secondary,
                "impedance_pu": branch.impedance_pu,
                "connection": branch.connection or "",
            }

            if flow is not None:
                props.update({
                    "p_kw": round(flow.p_kw, 2),
                    "q_kvar": round(flow.q_kvar, 2),
                    "s_kva": round(flow.s_kva, 2),
                    "loading_pct": round(flow.loading_pct, 2),
                    "losses_kw": round(flow.losses_kw, 4),
                    "compliance": flow.compliance.value,
                })
            else:
                props.update({
                    "p_kw": None, "q_kvar": None, "s_kva": None,
                    "loading_pct": 0.0, "losses_kw": None,
                    "compliance": "unknown",
                })

            features.append({
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": [x, y]},
            })

        return self._write_geojson_file(
            output_dir, "transformadores_resultados.geojson",
            features, name="Transformadores con resultados",
        )

    def _write_transformers_qml(self, output_dir: str) -> str:
        path = os.path.join(output_dir, "transformadores_resultados.qml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(qml_templates.qml_transformers_loading())
        return path

    # =========================================================================
    # SCRIPT LOADER PARA QGIS
    # =========================================================================
    def _write_loader_script(self, output_dir: str) -> str:
        """
        Genera un script Python que se pega en la consola QGIS para cargar
        las 3 capas con su simbología y zoom automático.
        """
        crs_raw = self.crs.replace("EPSG:", "")
        script = f'''# -*- coding: utf-8 -*-
"""
Script para cargar los resultados de redes_engine en QGIS.

Cómo usar:
    1. Abrir QGIS 3.16+
    2. Plugins → Python Console (Ctrl+Alt+P)
    3. Pegar este script y ejecutar
    4. Las 3 capas se cargan con su simbología automática
"""
import os
from qgis.core import QgsVectorLayer, QgsProject, QgsRectangle
from qgis.utils import iface

# Directorio donde están los archivos (modificar si es necesario)
RESULTS_DIR = r"{os.path.abspath(output_dir)}"

# CRS del proyecto (EPSG:{crs_raw})
project = QgsProject.instance()
project.setCrs(QgsProject.instance().crs().fromEpsgId({crs_raw}))

# ── Cargar capas ────────────────────────────────────────────────────
layers_info = [
    ("postes_resultados.geojson",          "Postes - Voltajes"),
    ("lineas_resultados.geojson",          "Líneas - Cargabilidad"),
    ("transformadores_resultados.geojson", "Transformadores"),
]

loaded = []
for filename, display_name in layers_info:
    path = os.path.join(RESULTS_DIR, filename)
    if not os.path.exists(path):
        print(f"⚠ Archivo no encontrado: {{path}}")
        continue
    layer = QgsVectorLayer(path, display_name, "ogr")
    if not layer.isValid():
        print(f"❌ Capa inválida: {{filename}}")
        continue

    # QGIS aplica automáticamente el .qml con mismo nombre base
    project.addMapLayer(layer)
    loaded.append(layer)
    print(f"✅ Cargada: {{display_name}} ({{layer.featureCount()}} features)")

# ── Zoom al extent total ────────────────────────────────────────────
if loaded:
    extent = QgsRectangle()
    extent.setMinimal()
    for layer in loaded:
        extent.combineExtentWith(layer.extent())
    iface.mapCanvas().setExtent(extent)
    iface.mapCanvas().refresh()
    print("\\n🗺 Zoom ajustado a la red completa.")

print(f"\\n✨ {{len(loaded)}} capas cargadas exitosamente.")
'''
        path = os.path.join(output_dir, "cargar_en_qgis.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        return path

    # =========================================================================
    # README explicativo
    # =========================================================================
    def _write_readme(self, output_dir: str) -> str:
        n_violations = (
            len(self.compliance.violations()) if self.compliance else 0
        )
        n_warnings = (
            len(self.compliance.warnings()) if self.compliance else 0
        )

        readme = f"""# Resultados redes_engine — Capas QGIS

Generado para la red: **{self.net.name}**

## Archivos en este directorio

| Archivo | Contenido |
|---|---|
| `postes_resultados.geojson` | Buses con voltaje, % caída y compliance |
| `postes_resultados.qml` | Simbología: círculos verde/amarillo/rojo |
| `lineas_resultados.geojson` | Líneas con flujo, corriente y % carga |
| `lineas_resultados.qml` | Simbología: gradiente de color y grosor |
| `transformadores_resultados.geojson` | Trafos con potencia y % utilización |
| `transformadores_resultados.qml` | Simbología: cuadrados categóricos |
| `cargar_en_qgis.py` | Script para QGIS Python Console |

## Cómo cargar en QGIS

### Opción 1: Drag & drop
Arrastrar los `.geojson` al canvas de QGIS — la simbología se aplica
automáticamente porque cada `.geojson` tiene su `.qml` hermano.

### Opción 2: Script automatizado
1. Abrir QGIS
2. Plugins → Python Console
3. Pegar el contenido de `cargar_en_qgis.py`
4. Ejecutar

## Resumen del análisis

- Buses analizados: {len(self.result.bus_voltages)}
- Líneas y trafos analizados: {len(self.result.branch_flows)}
- Pérdidas técnicas: {self.result.losses_pct:.2f}%
- Violaciones normativas: {n_violations}
- Advertencias: {n_warnings}

## Esquema de colores

**Postes:**
- 🟢 Verde   → cumple normativa (ΔV dentro de límite)
- 🟡 Naranja → advertencia (>80% del límite)
- 🔴 Rojo    → violación (excede límite ARCERNNR)

**Líneas (loading_pct):**
- 🟢 Verde   → 0-50% (subutilizada)
- 🟡 Amarillo→ 50-80% (operación normal)
- 🟠 Naranja → 80-100% (advertencia)
- 🔴 Rojo    → >100% (sobrecarga)

**Transformadores:**
- Cuadrados de mismo esquema verde/naranja/rojo
- Tamaño: 6/7/8 mm (mayor = más sobrecargado)
"""
        path = os.path.join(output_dir, "README.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(readme)
        return path

    # =========================================================================
    # Helper interno
    # =========================================================================
    def _write_geojson_file(
        self, output_dir: str, filename: str,
        features: list, name: str,
    ) -> str:
        crs_part = self.crs.split(":")[-1] if ":" in self.crs else self.crs
        feature_collection = {
            "type": "FeatureCollection",
            "name": name,
            "crs": {
                "type": "name",
                "properties": {
                    "name": f"urn:ogc:def:crs:EPSG::{crs_part}",
                },
            },
            "features": features,
        }
        path = os.path.join(output_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(feature_collection, f, ensure_ascii=False, indent=2)
        return path
