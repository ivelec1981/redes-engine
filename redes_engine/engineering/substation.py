# -*- coding: utf-8 -*-
"""
redes_engine.engineering.substation
=====================================

Módulo dedicado al diseño y análisis de **subestaciones eléctricas**
de distribución (típicamente 69/22.8 kV, 138/22.8 kV o 13.8 kV).

Cubre:
    - Modelo de subestación con barras MT/AT, transformadores principales,
      bahías de salida (alimentadores) y servicios auxiliares.
    - Cálculo de carga y reserva (N-1, N, esperanza de demanda).
    - Cálculo de cortocircuito en barras MT.
    - Selección de equipamiento: TC, TT, interruptores, seccionadores.
    - Reporte por subestación (factor de carga, reserva, capex).

Convenciones:
    - Tensión nominal AT (transmisión): kV línea-línea
    - Tensión nominal MT (distribución): kV línea-línea
    - MVA: capacidad nominal del transformador (placa)
    - Z%: impedancia porcentual nominal del transformador
    - Cooling stages típicos: ONAN < ONAF < ONAF2 (e.g. 7.5/10/12.5 MVA)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# =============================================================================
# Tipos / Enums
# =============================================================================
class SubstationTopology(Enum):
    """Esquemas de barra típicos en subestaciones de distribución."""
    SINGLE_BUS = "single_bus"          # 1 barra MT, 1 trafo
    SINGLE_BUS_TIE = "single_bus_tie"  # 1 barra con seccionador interbarra
    DOUBLE_BUS = "double_bus"          # 2 barras MT con TIE breaker
    RING_BUS = "ring_bus"              # configuración en anillo
    BREAKER_AND_HALF = "breaker_half"  # 1.5 interruptores (gran subestación)


class SubstationStatus(Enum):
    OK = "ok"
    WARNING = "warning"        # >80% capacidad
    OVERLOAD = "overload"      # >100% capacidad
    N_MINUS_1_FAIL = "n-1_fail"   # un trafo fuera la deja sobrecargada
    UNKNOWN = "unknown"


# =============================================================================
# Equipamiento básico
# =============================================================================
@dataclass
class PowerTransformer:
    """Transformador principal AT/MT de la subestación."""
    name: str
    rated_mva: float                      # placa ONAN
    rated_mva_onaf: Optional[float] = None  # placa con primer ventilador
    rated_mva_onaf2: Optional[float] = None # placa con todos los ventiladores
    voltage_at_kv: float = 69.0
    voltage_mt_kv: float = 22.8
    impedance_pct: float = 8.0            # Z% en base placa ONAN
    vector_group: str = "Dyn1"
    age_years: int = 0
    notes: str = ""

    @property
    def effective_capacity_mva(self) -> float:
        """Capacidad útil con todos los ventiladores activos."""
        if self.rated_mva_onaf2 is not None:
            return self.rated_mva_onaf2
        if self.rated_mva_onaf is not None:
            return self.rated_mva_onaf
        return self.rated_mva


@dataclass
class FeederBay:
    """Bahía de salida (un alimentador MT)."""
    name: str
    voltage_kv: float = 22.8
    rated_a: float = 600.0
    breaker_ka: float = 25.0           # capacidad de interrupción
    has_recloser: bool = False
    expected_load_mw: float = 0.0
    expected_load_mvar: float = 0.0


# =============================================================================
# Subestación
# =============================================================================
@dataclass
class Substation:
    """
    Modelo de subestación de distribución.

    Atributos
    ---------
    name : str
    topology : SubstationTopology
    transformers : List[PowerTransformer]
    feeders : List[FeederBay]
    short_circuit_at_at_bus_mva : float
        Aporte de cortocircuito en la barra de AT (3φ, MVA).
    aux_load_kw : float
        Servicios auxiliares (iluminación, refrigeración, control).
    """
    name: str
    topology: SubstationTopology = SubstationTopology.SINGLE_BUS
    transformers: List[PowerTransformer] = field(default_factory=list)
    feeders: List[FeederBay] = field(default_factory=list)
    short_circuit_at_at_bus_mva: float = 1500.0
    aux_load_kw: float = 50.0
    voltage_at_kv: float = 69.0
    voltage_mt_kv: float = 22.8
    has_capacitor_bank: bool = False
    capacitor_bank_kvar: float = 0.0

    # =========================================================================
    # Capacidad y carga
    # =========================================================================
    def total_capacity_mva(self) -> float:
        """Capacidad total instalada (suma de placas con cooling)."""
        return sum(t.effective_capacity_mva for t in self.transformers)

    def total_demand_mva(self) -> float:
        """Demanda esperada total (RMS de P y Q de los alimentadores)."""
        p = sum(f.expected_load_mw for f in self.feeders)
        q = sum(f.expected_load_mvar for f in self.feeders)
        return math.hypot(p, q)

    def loading_pct(self) -> float:
        """% de utilización con todos los trafos en servicio."""
        cap = self.total_capacity_mva()
        if cap <= 0:
            return 0.0
        return 100.0 * self.total_demand_mva() / cap

    def n_minus_1_capacity_mva(self) -> float:
        """Capacidad si el trafo más grande está fuera de servicio."""
        if len(self.transformers) <= 1:
            return 0.0
        ordered = sorted(
            self.transformers, key=lambda t: t.effective_capacity_mva,
            reverse=True,
        )
        return sum(t.effective_capacity_mva for t in ordered[1:])

    def n_minus_1_loading_pct(self) -> float:
        """% de utilización con criterio N-1."""
        cap = self.n_minus_1_capacity_mva()
        if cap <= 0:
            return float("inf")    # no hay redundancia
        return 100.0 * self.total_demand_mva() / cap

    def reserve_mva(self) -> float:
        """Reserva instalada (capacidad − demanda)."""
        return self.total_capacity_mva() - self.total_demand_mva()

    # =========================================================================
    # Cortocircuito en barra MT
    # =========================================================================
    def short_circuit_mt_bus_ka(self) -> float:
        """
        Corriente de cortocircuito 3φ aportada en la barra MT (kA).

        Combina:
            - Aporte del sistema AT (limitado por SCC_AT)
            - Impedancia de cada trafo (paralelos)
        Aproximación clásica:
            X_total_pu (sobre base trafo) = X_at + X_trafo
            I_cc = V_base / (sqrt(3) * X_total_ohm)
        """
        if not self.transformers or self.short_circuit_at_at_bus_mva <= 0:
            return 0.0
        v_mt = self.voltage_mt_kv
        # Combinar trafos en paralelo (admitancias)
        # Se usa un MVA base = capacidad total ONAN
        base_mva = sum(t.rated_mva for t in self.transformers)
        if base_mva <= 0:
            return 0.0
        # Z fuente AT en pu sobre base_mva
        z_at_pu = base_mva / self.short_circuit_at_at_bus_mva
        # Z paralelo de trafos en pu (cada uno en su base)
        # Convertimos cada Z_t a base_mva: Z_t_new = Z_t_pct/100 * base_mva/rated_t
        admittances = []
        for t in self.transformers:
            z_pu = (t.impedance_pct / 100.0) * (base_mva / t.rated_mva)
            if z_pu > 0:
                admittances.append(1.0 / z_pu)
        z_t_par = 1.0 / sum(admittances) if admittances else float("inf")
        z_total = z_at_pu + z_t_par
        if z_total <= 0:
            return 0.0
        scc_mva = base_mva / z_total
        # I_cc (kA) = SCC_mva / (sqrt(3) · V_kV)
        i_ka = scc_mva / (math.sqrt(3.0) * v_mt)
        return i_ka

    # =========================================================================
    # Diagnóstico de estado
    # =========================================================================
    def status(self) -> SubstationStatus:
        """Diagnóstico operativo según ARCERNNR Reg. 005/18 (criterio N-1).

        El criterio N-1 sólo aplica cuando hay ≥ 2 transformadores. Con un
        único trafo, la subestación no tiene redundancia por diseño y se
        evalúa únicamente por la carga nominal.
        """
        if not self.transformers:
            return SubstationStatus.UNKNOWN
        load_pct = self.loading_pct()
        if load_pct > 100:
            return SubstationStatus.OVERLOAD
        # Sólo evaluar N-1 si hay redundancia
        if len(self.transformers) >= 2:
            n1_pct = self.n_minus_1_loading_pct()
            if n1_pct > 100:
                return SubstationStatus.N_MINUS_1_FAIL
        if load_pct > 80:
            return SubstationStatus.WARNING
        return SubstationStatus.OK

    # =========================================================================
    # Reporte sintético
    # =========================================================================
    def summary(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "topology": self.topology.value,
            "n_transformers": len(self.transformers),
            "n_feeders": len(self.feeders),
            "total_capacity_mva": round(self.total_capacity_mva(), 2),
            "total_demand_mva": round(self.total_demand_mva(), 2),
            "loading_pct": round(self.loading_pct(), 1),
            "n_minus_1_loading_pct": round(self.n_minus_1_loading_pct(), 1)
                if self.n_minus_1_loading_pct() != float("inf") else None,
            "reserve_mva": round(self.reserve_mva(), 2),
            "short_circuit_mt_ka": round(self.short_circuit_mt_bus_ka(), 2),
            "status": self.status().value,
        }


# =============================================================================
# Catálogo (sub-set EEASA / CNEL)
# =============================================================================
STANDARD_TRANSFORMER_RATINGS_MVA = [
    1.0, 1.5, 2.0, 2.5, 3.75, 5.0, 7.5, 10.0, 12.5, 15.0, 20.0, 25.0, 33.33,
]


def select_transformer_for_load(
    demand_mva: float,
    n_units: int = 1,
    redundancy_n1: bool = True,
    margin_pct: float = 20.0,
) -> Optional[float]:
    """
    Sugiere el rating MVA por trafo dado un escenario de carga.

    Parameters
    ----------
    demand_mva : float
        Demanda total esperada.
    n_units : int
        Cantidad de transformadores (≥1).
    redundancy_n1 : bool
        Si True, dimensiona para que N-1 cubra la carga (cualquiera fuera
        deja capacidad ≥ demanda × (1+margin)).
    margin_pct : float
        Margen de reserva (%).

    Returns
    -------
    float or None : rating MVA por unidad, o None si demand_mva ≤ 0.
    """
    if demand_mva <= 0 or n_units < 1:
        return None
    margin = 1.0 + margin_pct / 100.0
    if redundancy_n1 and n_units > 1:
        # N-1: (n_units − 1) trafos deben cubrir demanda con margen
        required_each = demand_mva * margin / max(n_units - 1, 1)
    else:
        required_each = demand_mva * margin / n_units

    # Buscar la primera capacidad estándar ≥ requerida
    for rating in STANDARD_TRANSFORMER_RATINGS_MVA:
        if rating >= required_each:
            return rating
    return STANDARD_TRANSFORMER_RATINGS_MVA[-1]


# =============================================================================
# Constructor desde la red
# =============================================================================
def detect_substations(network) -> List[str]:
    """
    Identifica los buses tipo BARRA_SE en una red existente.

    Returns
    -------
    List[str] : ids de buses que son barras de subestación.
    """
    from ..core.graph import BusType
    return [
        b.id for b in network.buses.values()
        if b.bus_type == BusType.BARRA_SE
    ]
