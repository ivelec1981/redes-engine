# -*- coding: utf-8 -*-
"""
redes_engine.core.results
==========================

Dataclasses para resultados de simulación de flujo de potencia.

Después de resolver una red en OpenDSS, los resultados se empaquetan
en estructuras tipadas que permiten:
    - Inspección estructurada (sin tocar la API de OpenDSS)
    - Validación normativa (caída de voltaje, ampacidad)
    - Mapeo de vuelta a las capas QGIS para colorear el mapa
    - Exportación a Excel/JSON
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


# =============================================================================
# Estado de cumplimiento normativo
# =============================================================================
class ComplianceStatus(Enum):
    OK          = "ok"          # dentro de norma
    WARNING     = "warning"     # cerca del límite (>80% del margen)
    VIOLATION   = "violation"   # fuera de norma
    UNKNOWN     = "unknown"


# =============================================================================
# Resultado por Bus
# =============================================================================
@dataclass
class BusVoltageResult:
    """
    Resultado de tensión en un bus tras flujo de potencia.

    Attributes
    ----------
    bus_id : str
    v_magnitude_kv : float
        Magnitud de tensión línea-línea (kV).
    v_pu : float
        Tensión en por unidad (1.0 = nominal).
    v_drop_pct : float
        Caída relativa al voltaje nominal (%) — positivo = caída.
    angle_deg : float
        Ángulo de la fase A (grados).
    voltage_nominal_kv : float
        Tensión base del bus (kV).
    compliance : ComplianceStatus
        Estado normativo según ARCERNNR (MT: ±5%, BT: ±8%).
    """
    bus_id: str
    v_magnitude_kv: float
    v_pu: float
    v_drop_pct: float
    angle_deg: float
    voltage_nominal_kv: float
    compliance: ComplianceStatus = ComplianceStatus.UNKNOWN

    def is_mt(self) -> bool:
        return self.voltage_nominal_kv >= 1.0

    def evaluate_compliance(self,
                             mt_limit_pct: float = 5.0,
                             bt_limit_pct: float = 8.0) -> ComplianceStatus:
        """
        Evalúa cumplimiento según regulación ARCERNNR.

        Parameters
        ----------
        mt_limit_pct : float
            Límite de caída de voltaje en MT (%). Default 5%.
        bt_limit_pct : float
            Límite de caída de voltaje en BT (%). Default 8%.
        """
        limit = mt_limit_pct if self.is_mt() else bt_limit_pct
        magnitude = abs(self.v_drop_pct)
        if magnitude > limit:
            self.compliance = ComplianceStatus.VIOLATION
        elif magnitude > limit * 0.8:
            self.compliance = ComplianceStatus.WARNING
        else:
            self.compliance = ComplianceStatus.OK
        return self.compliance


# =============================================================================
# Resultado por Branch (línea o trafo)
# =============================================================================
@dataclass
class BranchFlowResult:
    """
    Resultado de flujo en un branch (línea o transformador).

    Attributes
    ----------
    branch_id : str
    p_kw : float
        Potencia activa (kW) que fluye desde bus_from hacia bus_to.
    q_kvar : float
        Potencia reactiva (kvar).
    s_kva : float
        Potencia aparente (kVA).
    current_a : float
        Corriente promedio (A).
    rated_a : float
        Corriente nominal del elemento.
    loading_pct : float
        Carga (%) respecto a la ampacidad.
    losses_kw : float
        Pérdidas activas en este elemento (kW).
    losses_kvar : float
        Pérdidas reactivas (kvar).
    compliance : ComplianceStatus
    """
    branch_id: str
    p_kw: float
    q_kvar: float
    s_kva: float
    current_a: float
    rated_a: float
    loading_pct: float
    losses_kw: float
    losses_kvar: float
    compliance: ComplianceStatus = ComplianceStatus.UNKNOWN
    is_transformer: bool = False

    def evaluate_compliance(self,
                             warning_pct: float = 80.0,
                             violation_pct: float = 100.0) -> ComplianceStatus:
        if self.loading_pct >= violation_pct:
            self.compliance = ComplianceStatus.VIOLATION
        elif self.loading_pct >= warning_pct:
            self.compliance = ComplianceStatus.WARNING
        else:
            self.compliance = ComplianceStatus.OK
        return self.compliance


# =============================================================================
# Resultado del sistema completo
# =============================================================================
@dataclass
class PowerFlowResult:
    """
    Resultado consolidado de un flujo de potencia.

    Attributes
    ----------
    converged : bool
    iterations : int
    total_power_kw : float
        Potencia activa total servida por la fuente (kW).
    total_power_kvar : float
    total_losses_kw : float
    total_losses_kvar : float
    losses_pct : float
        Pérdidas como % de la demanda total.
    bus_voltages : Dict[str, BusVoltageResult]
    branch_flows : Dict[str, BranchFlowResult]
    solver_message : str
    """
    converged: bool = False
    iterations: int = 0
    total_power_kw: float = 0.0
    total_power_kvar: float = 0.0
    # Potencia activa NETA con signo (+ = importación/demanda desde la fuente,
    # − = exportación neta hacia la red, p.ej. excedente PV). total_power_kw
    # conserva la magnitud por compatibilidad; net_power_kw permite separar
    # energía importada vs exportada en el análisis 8760h.
    net_power_kw: float = 0.0
    total_losses_kw: float = 0.0
    total_losses_kvar: float = 0.0
    losses_pct: float = 0.0
    bus_voltages: Dict[str, BusVoltageResult] = field(default_factory=dict)
    branch_flows: Dict[str, BranchFlowResult] = field(default_factory=dict)
    solver_message: str = ""

    # =========================================================================
    # Análisis agregado
    # =========================================================================

    def buses_in_violation(self) -> List[BusVoltageResult]:
        return [v for v in self.bus_voltages.values()
                if v.compliance == ComplianceStatus.VIOLATION]

    def buses_in_warning(self) -> List[BusVoltageResult]:
        return [v for v in self.bus_voltages.values()
                if v.compliance == ComplianceStatus.WARNING]

    def branches_overloaded(self) -> List[BranchFlowResult]:
        return [b for b in self.branch_flows.values()
                if b.compliance == ComplianceStatus.VIOLATION]

    def branches_in_warning(self) -> List[BranchFlowResult]:
        return [b for b in self.branch_flows.values()
                if b.compliance == ComplianceStatus.WARNING]

    def worst_voltage(self) -> Optional[BusVoltageResult]:
        if not self.bus_voltages:
            return None
        return max(self.bus_voltages.values(), key=lambda v: abs(v.v_drop_pct))

    def worst_loaded_branch(self) -> Optional[BranchFlowResult]:
        if not self.branch_flows:
            return None
        return max(self.branch_flows.values(), key=lambda b: b.loading_pct)

    # =========================================================================
    # Reportes
    # =========================================================================
    def summary(self) -> str:
        n_violations = len(self.buses_in_violation())
        n_warnings = len(self.buses_in_warning())
        n_overload = len(self.branches_overloaded())

        if not self.converged:
            cstatus = "❌ NO CONVERGIDO"
        elif n_violations or n_overload:
            cstatus = "⚠ CON VIOLACIONES NORMATIVAS"
        elif n_warnings:
            cstatus = "🟡 CON ADVERTENCIAS"
        else:
            cstatus = "✅ DENTRO DE NORMA"

        lines = [
            "═" * 64,
            "  RESULTADO DE FLUJO DE POTENCIA",
            "═" * 64,
            f"  Estado del solver        : {cstatus}",
            f"  Iteraciones              : {self.iterations}",
            f"  Potencia activa total    : {self.total_power_kw:>10,.2f} kW",
            f"  Potencia reactiva total  : {self.total_power_kvar:>10,.2f} kvar",
            f"  Pérdidas activas         : {self.total_losses_kw:>10,.3f} kW "
            f"({self.losses_pct:.2f}% de la demanda)",
            f"  Pérdidas reactivas       : {self.total_losses_kvar:>10,.3f} kvar",
            f"  ─────────────────────────────────────────────",
            f"  Buses analizados         : {len(self.bus_voltages)}",
            f"  Branches analizados      : {len(self.branch_flows)}",
            f"  ─────────────────────────────────────────────",
            f"  Violaciones de voltaje   : {n_violations}",
            f"  Advertencias de voltaje  : {n_warnings}",
            f"  Branches sobrecargados   : {n_overload}",
        ]

        worst_v = self.worst_voltage()
        if worst_v:
            lines.append(
                f"  Peor caída de voltaje    : {worst_v.bus_id} "
                f"= {worst_v.v_drop_pct:+.2f}% ({worst_v.compliance.value})"
            )
        worst_b = self.worst_loaded_branch()
        if worst_b:
            lines.append(
                f"  Branch más cargado       : {worst_b.branch_id} "
                f"= {worst_b.loading_pct:.1f}% ({worst_b.compliance.value})"
            )
        lines.append("═" * 64)
        return "\n".join(lines)

    def voltage_table(self, sort_by: str = "drop") -> str:
        """Tabla detallada de voltajes por bus."""
        lines = [
            "",
            "  BUS                 KV     PU      ΔV%      ÁNGULO  ESTADO",
            "  " + "─" * 60,
        ]

        if sort_by == "drop":
            sorted_buses = sorted(self.bus_voltages.values(),
                                   key=lambda v: -abs(v.v_drop_pct))
        else:
            sorted_buses = sorted(self.bus_voltages.values(),
                                   key=lambda v: v.bus_id)

        for v in sorted_buses:
            icon = {"ok": "✅", "warning": "🟡",
                    "violation": "❌", "unknown": "  "}[v.compliance.value]
            lines.append(
                f"  {v.bus_id:<18} {v.v_magnitude_kv:>6.3f} "
                f"{v.v_pu:>6.4f} {v.v_drop_pct:>+7.2f}% "
                f"{v.angle_deg:>+7.2f}°   {icon} {v.compliance.value}"
            )
        return "\n".join(lines)

    def branch_table(self) -> str:
        """Tabla de flujos en branches."""
        lines = [
            "",
            "  BRANCH        kW      kvar    A      LOAD%  LOSSES  ESTADO",
            "  " + "─" * 60,
        ]
        sorted_branches = sorted(self.branch_flows.values(),
                                  key=lambda b: -b.loading_pct)
        for b in sorted_branches:
            icon = {"ok": "✅", "warning": "🟡",
                    "violation": "❌", "unknown": "  "}[b.compliance.value]
            lines.append(
                f"  {b.branch_id:<10} {b.p_kw:>+7.2f} {b.q_kvar:>+7.2f} "
                f"{b.current_a:>6.1f} {b.loading_pct:>5.1f}% "
                f"{b.losses_kw:>5.2f}kW  {icon}"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialización a dict (para JSON)."""
        return {
            "converged": self.converged,
            "iterations": self.iterations,
            "total_power_kw": self.total_power_kw,
            "total_power_kvar": self.total_power_kvar,
            "total_losses_kw": self.total_losses_kw,
            "losses_pct": self.losses_pct,
            "buses": {
                bid: {
                    "v_kv": v.v_magnitude_kv,
                    "v_pu": v.v_pu,
                    "v_drop_pct": v.v_drop_pct,
                    "angle": v.angle_deg,
                    "compliance": v.compliance.value,
                } for bid, v in self.bus_voltages.items()
            },
            "branches": {
                bid: {
                    "p_kw": b.p_kw,
                    "q_kvar": b.q_kvar,
                    "current_a": b.current_a,
                    "loading_pct": b.loading_pct,
                    "losses_kw": b.losses_kw,
                    "compliance": b.compliance.value,
                } for bid, b in self.branch_flows.items()
            },
        }
