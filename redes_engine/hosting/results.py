# -*- coding: utf-8 -*-
"""
redes_engine.hosting.results
=============================

Estructuras tipadas para resultados de análisis de Host Capacity.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# =============================================================================
# Factor limitante
# =============================================================================
class LimitingFactor(Enum):
    """¿Qué restricción definió el límite de capacidad?"""
    NONE                = "none"               # nada limita (ilimitado)
    OVERVOLTAGE         = "overvoltage"        # V > 1.05 pu (PV inyectando)
    UNDERVOLTAGE        = "undervoltage"       # V < 0.92 pu (carga adicional)
    THERMAL_LINE        = "thermal_line"       # ampacidad de línea
    THERMAL_TRANSFORMER = "thermal_transformer"# trafo > 100%
    REVERSE_FLOW_TRAFO  = "reverse_flow_trafo" # flujo inverso por trafo
    CONVERGENCE_FAIL    = "convergence_fail"   # solver no convergió
    PRE_EXISTING        = "pre_existing"       # la red YA viola a 0 kW (sin candidato)


# =============================================================================
# Capacidad de alojamiento por bus
# =============================================================================
@dataclass
class BusHostingCapacity:
    """
    Capacidad de alojamiento de un bus específico.

    PV Hosting: cuánta generación distribuida puede instalarse antes de
    causar sobre-tensión, sobrecorriente inversa o sobrecarga del trafo.

    EV/Load Hosting: cuánta carga adicional puede conectarse antes de
    causar sub-tensión, sobrecorriente o sobrecarga del trafo.
    """
    bus_id: str
    voltage_nominal_kv: float

    # ── PV (generación) ──────────────────────────────────────────────
    pv_hosting_kw: float = 0.0
    pv_limiting_factor: LimitingFactor = LimitingFactor.NONE
    pv_limiting_hour: Optional[int] = None
    pv_limiting_element: str = ""           # bus/branch que falló primero
    pv_iterations: int = 0

    # ── Carga (VE / cargas nuevas) ───────────────────────────────────
    load_hosting_kw: float = 0.0
    load_limiting_factor: LimitingFactor = LimitingFactor.NONE
    load_limiting_hour: Optional[int] = None
    load_limiting_element: str = ""
    load_iterations: int = 0

    def total_iterations(self) -> int:
        return self.pv_iterations + self.load_iterations


# =============================================================================
# Resultado completo del análisis
# =============================================================================
@dataclass
class HostingCapacityResults:
    """
    Resultado consolidado del análisis de Host Capacity sobre toda la red.
    """
    network_name: str = ""
    n_buses_analyzed: int = 0
    n_hours_simulated_per_iteration: int = 0
    n_iterations_total: int = 0
    elapsed_seconds: float = 0.0
    method: str = "bisection"

    bus_results: Dict[str, BusHostingCapacity] = field(default_factory=dict)

    # =========================================================================
    # Análisis derivado
    # =========================================================================
    def best_pv_buses(self, n: int = 5) -> List[BusHostingCapacity]:
        """Top N buses con mayor capacidad PV."""
        return sorted(
            self.bus_results.values(),
            key=lambda b: -b.pv_hosting_kw,
        )[:n]

    def worst_pv_buses(self, n: int = 5) -> List[BusHostingCapacity]:
        """Top N buses con menor capacidad PV (saturados)."""
        return sorted(
            self.bus_results.values(),
            key=lambda b: b.pv_hosting_kw,
        )[:n]

    def best_load_buses(self, n: int = 5) -> List[BusHostingCapacity]:
        return sorted(
            self.bus_results.values(),
            key=lambda b: -b.load_hosting_kw,
        )[:n]

    def total_pv_capacity_kw(self) -> float:
        return sum(b.pv_hosting_kw for b in self.bus_results.values())

    def total_load_capacity_kw(self) -> float:
        return sum(b.load_hosting_kw for b in self.bus_results.values())

    def summary(self) -> str:
        lines = [
            "═" * 64,
            f"  HOST CAPACITY ANALYSIS — {self.network_name}",
            "═" * 64,
            f"  Buses analizados              : {self.n_buses_analyzed}",
            f"  Horas críticas por iteración  : {self.n_hours_simulated_per_iteration}",
            f"  Iteraciones totales            : {self.n_iterations_total}",
            f"  Tiempo total                   : {self.elapsed_seconds:.1f} s",
            f"  Método                         : {self.method}",
            "─" * 64,
            f"  Capacidad TOTAL de PV         : "
            f"{self.total_pv_capacity_kw():,.1f} kW",
            f"  Capacidad TOTAL de carga       : "
            f"{self.total_load_capacity_kw():,.1f} kW",
            "═" * 64,
        ]
        return "\n".join(lines)

    def ranking_table(self, n: int = 10) -> str:
        lines = [
            "",
            "  CAPACIDAD POR BUS — TOP " + str(n),
            "  " + "─" * 78,
            f"  {'Bus':<14} {'V nom':>7} {'PV kW':>10} {'Limita PV':>22} "
            f"{'Carga kW':>10} {'Limita Carga':>22}",
            "  " + "─" * 78,
        ]
        # Ordenar por suma PV+Load capacity
        sorted_buses = sorted(
            self.bus_results.values(),
            key=lambda b: -(b.pv_hosting_kw + b.load_hosting_kw),
        )[:n]
        for b in sorted_buses:
            lines.append(
                f"  {b.bus_id:<14} {b.voltage_nominal_kv:>6.2f}kV "
                f"{b.pv_hosting_kw:>9.1f} {b.pv_limiting_factor.value:>22} "
                f"{b.load_hosting_kw:>9.1f} {b.load_limiting_factor.value:>22}"
            )
        return "\n".join(lines)
