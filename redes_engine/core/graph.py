# -*- coding: utf-8 -*-
"""
redes_engine.core.graph
========================

Modelo de datos del grafo eléctrico unificado.

Tres entidades fundamentales:
    Bus     — nodo del grafo (poste, pozo, medidor, barra)
    Branch  — arista del grafo (línea, transformador, switch)
    Asset   — activo conectado a un bus (carga, VE, PV, BESS, V2G)

Principio rector:
    El motor NO distingue entre red MT y red BT. Recibe un grafo
    multinivel donde el TRANSFORMADOR es simplemente una arista
    especial que conecta dos buses con voltajes distintos.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

# =============================================================================
# ENUMS
# =============================================================================

class VoltageLevel(Enum):
    """Niveles de voltaje estándar Ecuador + DC fast charging."""
    SUB_TRANS_69KV = 69.0       # Subtransmisión
    MT_22_8KV      = 22.8       # MT estándar EEQ/CNEL/EEASA
    MT_13_8KV      = 13.8       # MT alternativa
    MT_6_3KV       = 6.3        # MT industrial legacy
    BT_220_127     = 0.220      # BT trifásica 220/127 V
    BT_240_120     = 0.240      # BT bifásica 240/120 V
    DC_BUS_480     = 0.480      # DC bus para fast charging
    DC_BUS_750     = 0.750      # DC bus ultra-fast charging


class BusType(Enum):
    """Tipos de nodos del grafo eléctrico."""
    POSTE_MT      = "poste_mt"        # poste con conductor de MT
    POSTE_BT      = "poste_bt"        # poste con conductor de BT
    POZO_MT       = "pozo_mt"         # pozo subterráneo MT
    POZO_BT       = "pozo_bt"         # pozo subterráneo BT
    NODO_TRAFO    = "nodo_trafo"      # punto de cambio de voltaje
    MEDIDOR       = "medidor"         # punto de entrega al cliente
    BARRA_SE      = "barra_se"        # barra de subestación
    NODO_VIRTUAL  = "virtual"         # punto auxiliar de cálculo


class BranchType(Enum):
    """Tipos de aristas del grafo eléctrico."""
    LINE_AEREA_MT       = "linea_aerea_mt"
    LINE_AEREA_BT       = "linea_aerea_bt"
    LINE_SOTERRADA_MT   = "linea_soterrada_mt"
    LINE_SOTERRADA_BT   = "linea_soterrada_bt"
    TRANSFORMER         = "transformer"     # cambio de voltaje
    SWITCH              = "switch"          # seccionador NO o NC
    RECLOSER            = "recloser"        # reconectador automático
    FUSE                = "fuse"            # fusible
    REGULATOR           = "regulator"       # regulador de voltaje


class AssetType(Enum):
    """Tipos de activos que se conectan a los buses."""
    # ── Cargas pasivas ───────────────────────────────────────────────
    LOAD_RESIDENCIAL    = "load_residencial"
    LOAD_COMERCIAL      = "load_comercial"
    LOAD_INDUSTRIAL     = "load_industrial"
    ALUMBRADO_PUBLICO   = "alumbrado"

    # ── Movilidad eléctrica ──────────────────────────────────────────
    EV_CHARGER_AC_L1    = "ev_ac_l1"        # 1.4–1.9 kW
    EV_CHARGER_AC_L2    = "ev_ac_l2"        # 7–22 kW
    EV_CHARGER_DC_FAST  = "ev_dc_fast"      # 50–150 kW
    EV_CHARGER_DC_ULTRA = "ev_dc_ultra"     # 350–400 kW
    EV_FLEET_DEPOT      = "ev_depot"        # múltiples cargadores

    # ── Generación distribuida ───────────────────────────────────────
    SOLAR_PV_RESID      = "pv_resid"        # 3–10 kWp
    SOLAR_PV_COMERCIAL  = "pv_comercial"    # 50–500 kWp
    SOLAR_PV_UTILITY    = "pv_utility"      # >1 MWp
    EOLICO              = "eolico"
    COGENERACION        = "cogen"

    # ── Almacenamiento ───────────────────────────────────────────────
    BESS_BTM            = "bess_btm"        # behind-the-meter (residencial)
    BESS_C_AND_I        = "bess_ci"         # commercial & industrial
    BESS_GRID_SCALE     = "bess_grid"       # >1 MWh distribución

    # ── Híbridos / Bidireccionales ───────────────────────────────────
    PV_BESS_HYBRID      = "pv_bess"         # solar + batería
    V2G_BIDIRECTIONAL   = "v2g"             # VE bidireccional


# =============================================================================
# ENTIDADES DEL GRAFO
# =============================================================================

@dataclass
class Bus:
    """
    Nodo del grafo eléctrico.

    Representa un punto físico de intercambio de energía.
    Puede ser un poste, un pozo, un medidor o una barra de subestación.

    Attributes
    ----------
    id : str
        Identificador único.
    geometry : (float, float)
        Coordenadas (x, y) en sistema proyectado (típicamente EPSG:32717).
    voltage_kv : float
        Voltaje nominal en este punto (kV).
    level : VoltageLevel
        Categoría de nivel de voltaje.
    bus_type : BusType
        Tipo físico del nodo.
    elevation_m : float
        Cota sobre el nivel del mar (m). Usada en cálculo mecánico.
    zone : str | None
        Identificador del alimentador/circuito padre.
    """
    id: str
    geometry: Tuple[float, float]
    voltage_kv: float
    level: VoltageLevel
    bus_type: BusType
    elevation_m: float = 0.0
    zone: Optional[str] = None

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Bus) and self.id == other.id

    def is_mt(self) -> bool:
        """¿Este bus pertenece a media tensión?"""
        return self.voltage_kv >= 1.0

    def is_bt(self) -> bool:
        """¿Este bus pertenece a baja tensión?"""
        return self.voltage_kv < 1.0


@dataclass
class Branch:
    """
    Arista del grafo eléctrico.

    Conecta dos buses y representa un elemento físico de transferencia:
    línea aérea, cable subterráneo, transformador, switch, fusible, etc.

    Para líneas: r_ohm, x_ohm son TOTALES (no por km).
    Para transformadores: usar kva, kv_primary, kv_secondary, impedance_pu.
    """
    id: str
    bus_from: str
    bus_to: str
    branch_type: BranchType
    geometry: List[Tuple[float, float]]
    length_m: float
    # ── Eléctricas ───────────────────────────────────────────────────
    r_ohm: float = 0.0
    x_ohm: float = 0.0
    b_us: float = 0.0
    rated_a: float = 0.0
    # ── Mecánicas (solo aéreas) ──────────────────────────────────────
    conductor_type: Optional[str] = None
    span_max_m: Optional[float] = None
    # ── Transformador (solo si branch_type=TRANSFORMER) ──────────────
    kva: Optional[float] = None
    kv_primary: Optional[float] = None
    kv_secondary: Optional[float] = None
    connection: Optional[str] = None        # "Dyn1", "Yyn0", etc.
    impedance_pu: Optional[float] = None    # %Z en pu
    # ── Switch / Recloser / Fuse ─────────────────────────────────────
    is_open: bool = False                   # estado para switches/reclosers
    rated_ka_break: Optional[float] = None  # capacidad de interrupción

    def is_line(self) -> bool:
        """¿Es una línea (aérea o subterránea)?"""
        return self.branch_type in (
            BranchType.LINE_AEREA_MT, BranchType.LINE_AEREA_BT,
            BranchType.LINE_SOTERRADA_MT, BranchType.LINE_SOTERRADA_BT,
        )

    def is_transformer(self) -> bool:
        return self.branch_type == BranchType.TRANSFORMER


@dataclass
class Asset:
    """
    Activo conectado a un bus.

    Representa una carga, generador, almacenamiento o cargador VE
    que se "engancha" a un Bus existente.

    El motor de cálculo es agnóstico al asset_type — solo lee:
        rated_kw, profile_24h_kw, controllable, bidirectional, capacity_kwh

    Attributes
    ----------
    id : str
        Identificador único.
    bus_id : str
        ID del bus al cual está conectado.
    asset_type : AssetType
        Tipo de activo (define la semántica).
    rated_kw : float
        Potencia nominal del activo (kW). Positivo=consumo, negativo=generación.
    rated_kvar : float
        Potencia reactiva nominal (kvar).
    profile_24h_kw : list[float] | None
        Curva diaria 24 valores (kW por hora). Si None, usa rated_kw constante.
    profile_annual_kwh : float | None
        Energía anual estimada (kWh). Para escalar perfil al consumo real.
    controllable : bool
        ¿El operador puede gestionar este activo (BESS, VE smart)?
    bidirectional : bool
        ¿Puede inyectar a la red (V2G, BESS)?
    capacity_kwh : float | None
        Capacidad de almacenamiento (BESS, V2G).
    soc_initial : float | None
        Estado de carga inicial [0,1].
    efficiency_charge : float | None
        Eficiencia de carga del BESS [0,1].
    efficiency_discharge : float | None
        Eficiencia de descarga del BESS [0,1].
    capacity_factor : float | None
        Factor de planta (PV, eólico) [0,1].
    generation_profile : list[float] | None
        Curva 24h de generación (PV depende de irradiancia).
    """
    id: str
    bus_id: str
    asset_type: AssetType
    rated_kw: float
    rated_kvar: float = 0.0
    profile_24h_kw: Optional[List[float]] = None
    profile_annual_kwh: Optional[float] = None
    controllable: bool = False
    bidirectional: bool = False
    capacity_kwh: Optional[float] = None
    soc_initial: Optional[float] = 0.5
    efficiency_charge: Optional[float] = 0.95
    efficiency_discharge: Optional[float] = 0.95
    capacity_factor: Optional[float] = None
    generation_profile: Optional[List[float]] = None

    # ── Categorías ───────────────────────────────────────────────────
    def is_load(self) -> bool:
        return self.asset_type in (
            AssetType.LOAD_RESIDENCIAL, AssetType.LOAD_COMERCIAL,
            AssetType.LOAD_INDUSTRIAL, AssetType.ALUMBRADO_PUBLICO,
        )

    def is_ev(self) -> bool:
        return self.asset_type in (
            AssetType.EV_CHARGER_AC_L1, AssetType.EV_CHARGER_AC_L2,
            AssetType.EV_CHARGER_DC_FAST, AssetType.EV_CHARGER_DC_ULTRA,
            AssetType.EV_FLEET_DEPOT, AssetType.V2G_BIDIRECTIONAL,
        )

    def is_pv(self) -> bool:
        return self.asset_type in (
            AssetType.SOLAR_PV_RESID, AssetType.SOLAR_PV_COMERCIAL,
            AssetType.SOLAR_PV_UTILITY, AssetType.PV_BESS_HYBRID,
        )

    def is_storage(self) -> bool:
        return self.asset_type in (
            AssetType.BESS_BTM, AssetType.BESS_C_AND_I,
            AssetType.BESS_GRID_SCALE, AssetType.PV_BESS_HYBRID,
            AssetType.V2G_BIDIRECTIONAL,
        )

    def is_generator(self) -> bool:
        return self.is_pv() or self.asset_type in (
            AssetType.EOLICO, AssetType.COGENERACION,
        )

    # ── Acceso a perfil ──────────────────────────────────────────────
    def power_at_hour(self, hour: int) -> float:
        """Devuelve potencia (kW) en una hora dada [0,23]."""
        if self.profile_24h_kw is not None and 0 <= hour < len(self.profile_24h_kw):
            return self.profile_24h_kw[hour]
        return self.rated_kw
