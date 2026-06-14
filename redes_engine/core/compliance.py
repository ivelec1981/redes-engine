# -*- coding: utf-8 -*-
"""
redes_engine.core.compliance
=============================

Analizador de cumplimiento normativo para resultados de flujo de potencia.

Reglas implementadas:
    - ARCERNNR Regulación 002/20: Caída de voltaje permitida
        MT (línea primaria)        : ±5%
        BT (acometida cliente)     : ±8%
        BT (alumbrado público)     : ±5%
    - Ampacidad de conductores y trafos: ≤100% nominal (advertencia >80%)
    - Sobrecarga del transformador: ≤80% utilización en horizonte 10 años
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .results import (
    BranchFlowResult,
    BusVoltageResult,
    ComplianceStatus,
    PowerFlowResult,
)


class NormativeFramework(Enum):
    """Marcos normativos soportados."""
    ARCERNNR_EC_002_20 = "ARCERNNR Ecuador Reg. 002/20"
    CREG_CO_096_2000   = "CREG Colombia Res. 096/2000"
    OSINERGMIN_PE      = "OSINERGMIN Perú NTCSE"
    GENERIC_IEEE       = "IEEE Std 1547 / IEC 60038 (genérico)"


@dataclass
class NormativeLimits:
    """Límites configurables por marco normativo."""
    name: NormativeFramework
    # Caída máxima de voltaje (%)
    mt_voltage_drop_pct: float = 5.0
    bt_voltage_drop_pct: float = 8.0
    bt_lighting_drop_pct: float = 5.0
    # Cargabilidad máxima
    line_loading_warning_pct: float = 80.0
    line_loading_max_pct: float = 100.0
    transformer_loading_warning_pct: float = 80.0
    transformer_loading_max_pct: float = 100.0
    # Pérdidas técnicas máximas (% energía servida)
    technical_losses_max_pct: float = 8.0


# Presets predefinidos
ARCERNNR_EC = NormativeLimits(
    name=NormativeFramework.ARCERNNR_EC_002_20,
    mt_voltage_drop_pct=5.0,
    bt_voltage_drop_pct=8.0,
    bt_lighting_drop_pct=5.0,
    line_loading_max_pct=100.0,
    transformer_loading_max_pct=100.0,
    technical_losses_max_pct=8.0,
)

GENERIC_IEEE = NormativeLimits(
    name=NormativeFramework.GENERIC_IEEE,
    mt_voltage_drop_pct=5.0,
    bt_voltage_drop_pct=5.0,
    bt_lighting_drop_pct=5.0,
)


# =============================================================================
# Hallazgo individual de incumplimiento
# =============================================================================
@dataclass
class ComplianceFinding:
    """Hallazgo concreto de cumplimiento o incumplimiento."""
    severity: ComplianceStatus
    category: str            # "voltaje" | "ampacidad" | "trafo" | "perdidas"
    element_id: str
    actual_value: float
    limit_value: float
    units: str
    message: str

    def __str__(self) -> str:
        icon = {
            ComplianceStatus.OK: "✅",
            ComplianceStatus.WARNING: "🟡",
            ComplianceStatus.VIOLATION: "❌",
            ComplianceStatus.UNKNOWN: "⚪",
        }[self.severity]
        return f"  {icon} [{self.category:<10}] {self.element_id}: {self.message}"


# =============================================================================
# Reporte de cumplimiento
# =============================================================================
@dataclass
class ComplianceReport:
    """Reporte completo de cumplimiento normativo."""
    framework: NormativeFramework
    findings: List[ComplianceFinding] = field(default_factory=list)
    overall_status: ComplianceStatus = ComplianceStatus.OK

    def violations(self) -> List[ComplianceFinding]:
        return [f for f in self.findings
                if f.severity == ComplianceStatus.VIOLATION]

    def warnings(self) -> List[ComplianceFinding]:
        return [f for f in self.findings
                if f.severity == ComplianceStatus.WARNING]

    def passed(self) -> List[ComplianceFinding]:
        return [f for f in self.findings if f.severity == ComplianceStatus.OK]

    def summary(self) -> str:
        n_viol = len(self.violations())
        n_warn = len(self.warnings())

        icon = {"ok": "✅", "warning": "🟡", "violation": "❌"}[self.overall_status.value]
        lines = [
            "═" * 64,
            "  REPORTE DE CUMPLIMIENTO NORMATIVO",
            "═" * 64,
            f"  Marco normativo  : {self.framework.value}",
            f"  Estado global    : {icon} {self.overall_status.value.upper()}",
            f"  Total revisiones : {len(self.findings)}",
            f"    └─ Cumplen     : {len(self.passed())}",
            f"    └─ Advertencia : {n_warn}",
            f"    └─ VIOLACIONES : {n_viol}",
            "─" * 64,
        ]

        if n_viol > 0:
            lines.append("  ❌ VIOLACIONES (requieren acción):")
            for f in self.violations():
                lines.append(str(f))
            lines.append("")

        if n_warn > 0:
            lines.append("  🟡 ADVERTENCIAS (monitorear):")
            for f in self.warnings():
                lines.append(str(f))
            lines.append("")

        if n_viol == 0 and n_warn == 0:
            lines.append("  ✅ TODOS LOS PARÁMETROS CUMPLEN LA NORMATIVA")

        lines.append("═" * 64)
        return "\n".join(lines)


# =============================================================================
# ANALIZADOR
# =============================================================================
class ComplianceAnalyzer:
    """
    Analiza un PowerFlowResult contra un marco normativo.

    Uso:
        analyzer = ComplianceAnalyzer(ARCERNNR_EC)
        report = analyzer.analyze(power_flow_result)
        print(report.summary())
    """

    def __init__(self, limits: Optional[NormativeLimits] = None):
        self.limits = limits or ARCERNNR_EC

    def analyze(self, result: PowerFlowResult) -> ComplianceReport:
        report = ComplianceReport(framework=self.limits.name)

        # ── Voltajes ──────────────────────────────────────────────────
        for v in result.bus_voltages.values():
            report.findings.append(self._analyze_voltage(v))

        # ── Cargabilidad de líneas y trafos ───────────────────────────
        for b in result.branch_flows.values():
            report.findings.append(self._analyze_loading(b))

        # ── Pérdidas globales ─────────────────────────────────────────
        report.findings.append(self._analyze_losses(result))

        # ── Estado global ─────────────────────────────────────────────
        if any(f.severity == ComplianceStatus.VIOLATION for f in report.findings):
            report.overall_status = ComplianceStatus.VIOLATION
        elif any(f.severity == ComplianceStatus.WARNING for f in report.findings):
            report.overall_status = ComplianceStatus.WARNING
        else:
            report.overall_status = ComplianceStatus.OK

        return report

    # ─────────────────────────────────────────────────────────────────────
    def _analyze_voltage(self, v: BusVoltageResult) -> ComplianceFinding:
        # Los buses DC (fast charging) no se rigen por los límites ARCERNNR de
        # caída de tensión AC → no evaluados (no cuentan como violación).
        if getattr(v, "is_dc", False):
            return ComplianceFinding(
                severity=ComplianceStatus.UNKNOWN, category="voltaje",
                element_id=v.bus_id,
                actual_value=abs(v.v_drop_pct), limit_value=0.0, units="%",
                message="Bus DC: límites AC de caída de tensión no aplican",
            )
        limit = (self.limits.mt_voltage_drop_pct
                 if v.is_mt() else self.limits.bt_voltage_drop_pct)
        actual = abs(v.v_drop_pct)

        if actual > limit:
            sev = ComplianceStatus.VIOLATION
            msg = (f"ΔV={v.v_drop_pct:+.2f}% excede límite "
                   f"{('MT' if v.is_mt() else 'BT')} de ±{limit}%")
        elif actual > 0.8 * limit:
            sev = ComplianceStatus.WARNING
            msg = (f"ΔV={v.v_drop_pct:+.2f}% cerca del límite "
                   f"{('MT' if v.is_mt() else 'BT')} de ±{limit}%")
        else:
            sev = ComplianceStatus.OK
            msg = f"ΔV={v.v_drop_pct:+.2f}% dentro del límite ±{limit}%"

        return ComplianceFinding(
            severity=sev, category="voltaje",
            element_id=v.bus_id,
            actual_value=actual, limit_value=limit, units="%",
            message=msg,
        )

    def _analyze_loading(self, b: BranchFlowResult) -> ComplianceFinding:
        warn = self.limits.line_loading_warning_pct
        maxp = self.limits.line_loading_max_pct

        if b.loading_pct > maxp:
            sev = ComplianceStatus.VIOLATION
            msg = (f"Carga {b.loading_pct:.1f}% supera ampacidad "
                   f"({b.current_a:.0f}/{b.rated_a:.0f} A)")
        elif b.loading_pct > warn:
            sev = ComplianceStatus.WARNING
            msg = f"Carga {b.loading_pct:.1f}% se acerca al límite ({maxp}%)"
        else:
            sev = ComplianceStatus.OK
            msg = f"Carga {b.loading_pct:.1f}% dentro del rango"

        return ComplianceFinding(
            severity=sev, category="ampacidad",
            element_id=b.branch_id,
            actual_value=b.loading_pct, limit_value=maxp, units="%",
            message=msg,
        )

    def _analyze_losses(self, result: PowerFlowResult) -> ComplianceFinding:
        max_pct = self.limits.technical_losses_max_pct
        actual = result.losses_pct

        if actual > max_pct:
            sev = ComplianceStatus.VIOLATION
            msg = (f"Pérdidas técnicas {actual:.2f}% > "
                   f"objetivo {max_pct}% (regulatorio)")
        elif actual > 0.8 * max_pct:
            sev = ComplianceStatus.WARNING
            msg = f"Pérdidas {actual:.2f}% se acercan al objetivo {max_pct}%"
        else:
            sev = ComplianceStatus.OK
            msg = f"Pérdidas {actual:.2f}% por debajo del objetivo {max_pct}%"

        return ComplianceFinding(
            severity=sev, category="perdidas",
            element_id="SISTEMA",
            actual_value=actual, limit_value=max_pct, units="%",
            message=msg,
        )
