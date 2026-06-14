# -*- coding: utf-8 -*-
"""
redes_engine.engineering.investment
=====================================

Análisis de inversión multianual (CAPEX + OPEX + flujo de caja descontado).

Cubre:
    - CAPEX inicial: BOM × precios + costos indirectos (instalación, ingeniería)
    - OPEX anual: O&M, pérdidas técnicas, reemplazos
    - Beneficios: reducción pérdidas, deferred capacity, ingresos VE/PV
    - Indicadores financieros: VAN, TIR, payback, LCOE/LCOS

Convención de signos:
    Flujo positivo  = ingreso / ahorro (entra a la empresa)
    Flujo negativo  = egreso / inversión (sale de la empresa)

Tasa de descuento: 10% nominal (referencia ARCERNNR/CENACE Ecuador).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# =============================================================================
# Configuración del análisis
# =============================================================================
@dataclass
class InvestmentAssumptions:
    """Parámetros financieros del análisis."""
    horizon_years: int = 5
    discount_rate: float = 0.10
    inflation_rate: float = 0.03
    energy_tariff_usd_per_kwh: float = 0.092      # tarifa promedio Ecuador 2026
    losses_compensation_usd_per_kwh: float = 0.075   # costo marginal pérdidas
    om_pct_of_capex_per_year: float = 0.02        # 2% anual O&M
    indirect_costs_pct: float = 0.18              # ingeniería+instalación+SCM
    contingency_pct: float = 0.10                 # contingencia 10%
    capex_inflation_pct_per_year: float = 0.0     # CAPEX no recurrente
    deferred_capex_usd: float = 0.0               # capacity diferida (subestación, ampliación)
    project_lifetime_years: int = 25              # vida útil para depreciación


@dataclass
class CashFlow:
    """Flujo de caja anual desglosado."""
    year: int
    capex_usd: float = 0.0
    opex_om_usd: float = 0.0
    opex_losses_usd: float = 0.0
    revenue_savings_usd: float = 0.0
    revenue_other_usd: float = 0.0
    net_usd: float = 0.0


@dataclass
class InvestmentResult:
    """Resultado del análisis de inversión."""
    capex_total_usd: float
    cashflows: List[CashFlow]
    npv_usd: float
    irr_pct: Optional[float]
    payback_years: Optional[float]
    benefit_cost_ratio: Optional[float]
    annual_summary: Dict[int, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def cumulative_cashflow(self) -> List[float]:
        cumulative = []
        s = 0.0
        for cf in self.cashflows:
            s += cf.net_usd
            cumulative.append(s)
        return cumulative

    def summary_lines(self) -> List[str]:
        lines = [
            "═" * 60,
            "  ANÁLISIS DE INVERSIÓN",
            "═" * 60,
            f"  CAPEX inicial            : USD {self.capex_total_usd:,.2f}",
            f"  Horizonte                : {len(self.cashflows)} años",
            f"  VAN (10%)                : USD {self.npv_usd:,.2f}",
            f"  TIR                      : "
            f"{self.irr_pct:.1f}%" if self.irr_pct is not None else
            "  TIR                      : (no calculable)",
            f"  Payback                  : "
            f"{self.payback_years:.2f} años" if self.payback_years is not None
            else "  Payback                  : > horizonte",
            f"  Relación beneficio/costo : "
            f"{self.benefit_cost_ratio:.2f}" if self.benefit_cost_ratio is not None
            else "  Relación beneficio/costo : (n/d)",
            "═" * 60,
        ]
        return lines


# =============================================================================
# Indicadores financieros
# =============================================================================
def npv(rate: float, cashflows: List[float]) -> float:
    """Valor Actual Neto."""
    if rate <= -1.0:
        raise ValueError("Tasa de descuento inválida")
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(cashflows))


def irr(cashflows: List[float],
        guess: float = 0.10,
        tol: float = 1e-6,
        max_iter: int = 200) -> Optional[float]:
    """
    Tasa Interna de Retorno por bisección sobre [-0.99, +10.0].

    Returns
    -------
    float or None : IRR en por unidad. None si no hay cambio de signo.
    """
    if not cashflows:
        return None
    has_pos = any(c > 0 for c in cashflows)
    has_neg = any(c < 0 for c in cashflows)
    if not (has_pos and has_neg):
        return None

    lo, hi = -0.99, 10.0
    f_lo = npv(lo, cashflows)
    f_hi = npv(hi, cashflows)
    if f_lo * f_hi > 0:
        # Sin cambio de signo en el rango, fallback Newton-like
        rate = guess
        for _ in range(max_iter):
            f = npv(rate, cashflows)
            if abs(f) < tol:
                return rate
            # Derivada numérica
            dr = max(abs(rate) * 1e-4, 1e-6)
            df = (npv(rate + dr, cashflows) - f) / dr
            if abs(df) < 1e-12:
                return None
            new_rate = rate - f / df
            if abs(new_rate - rate) < tol:
                return new_rate
            rate = new_rate
        return None

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid, cashflows)
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2.0


def payback_period(cashflows: List[float]) -> Optional[float]:
    """
    Payback con interpolación lineal entre el año previo y el año en que
    el flujo acumulado cruza cero. None si no se recupera la inversión.
    """
    cumulative = 0.0
    prev_cum = 0.0
    for t, cf in enumerate(cashflows):
        prev_cum = cumulative
        cumulative += cf
        if cumulative >= 0 and prev_cum < 0:
            # Interpolación lineal
            if cf == 0:
                return float(t)
            return (t - 1) + (-prev_cum) / cf
    return None


# =============================================================================
# Cálculo de beneficios anuales
# =============================================================================
def estimate_annual_loss_savings_kwh(
    losses_kwh_baseline: float,
    losses_kwh_with_project: float,
) -> float:
    """Energía anual ahorrada por reducción de pérdidas (kWh)."""
    return max(0.0, losses_kwh_baseline - losses_kwh_with_project)


# =============================================================================
# Engine principal
# =============================================================================
class InvestmentAnalyzer:
    """
    Genera el análisis financiero del proyecto.

    Uso típico:
        a = InvestmentAnalyzer(assumptions)
        result = a.analyze(
            capex_direct_usd=180_000,
            annual_loss_savings_kwh=45_000,
            annual_capacity_savings_usd=12_000,
        )
    """

    def __init__(self, assumptions: Optional[InvestmentAssumptions] = None):
        self.a = assumptions or InvestmentAssumptions()

    # =========================================================================
    # CAPEX total con costos indirectos
    # =========================================================================
    def total_capex(self, capex_direct_usd: float) -> float:
        """CAPEX total = directo × (1 + indirectos) × (1 + contingencia)."""
        if capex_direct_usd < 0:
            raise ValueError("CAPEX directo no puede ser negativo")
        with_indirect = capex_direct_usd * (1.0 + self.a.indirect_costs_pct)
        with_contingency = with_indirect * (1.0 + self.a.contingency_pct)
        return with_contingency

    # =========================================================================
    # Análisis multianual
    # =========================================================================
    def analyze(
        self,
        capex_direct_usd: float,
        annual_loss_savings_kwh: float = 0.0,
        annual_capacity_savings_usd: float = 0.0,
        annual_other_revenue_usd: float = 0.0,
        capex_year: int = 0,
    ) -> InvestmentResult:
        """
        Genera el flujo de caja anual y los indicadores.

        Parameters
        ----------
        capex_direct_usd : float
            CAPEX directo del proyecto (USD).
        annual_loss_savings_kwh : float
            Reducción anual de pérdidas técnicas (kWh).
        annual_capacity_savings_usd : float
            Capacidad diferida (subestación, ampliación) en USD/año.
        annual_other_revenue_usd : float
            Otros ingresos anuales (rebates, créditos de carbono, etc.).
        capex_year : int
            Año en que se ejecuta el CAPEX (0 = inversión inicial).

        Returns
        -------
        InvestmentResult
        """
        if self.a.horizon_years < 1:
            raise ValueError("horizon_years debe ser ≥ 1")

        capex_total = self.total_capex(capex_direct_usd)
        cashflows: List[CashFlow] = []
        notes: List[str] = []

        for t in range(self.a.horizon_years + 1):
            cf = CashFlow(year=t)

            # CAPEX (típicamente solo en t=0)
            if t == capex_year:
                cf.capex_usd = -capex_total

            # OPEX y beneficios solo DESPUÉS de ejecutar la inversión: el activo
            # no opera (ni ahorra) antes de existir. Para capex_year>0 esto
            # evita generar ingresos en años previos a la inversión.
            if t > capex_year:
                # Inflación acumulada (relativa al primer año de operación)
                inflation_factor = (
                    (1.0 + self.a.inflation_rate) ** (t - capex_year - 1)
                )

                # OPEX
                cf.opex_om_usd = -capex_total * self.a.om_pct_of_capex_per_year
                cf.opex_losses_usd = 0.0   # ya neto (savings van a revenue)

                # Revenue: ahorro de pérdidas + capacity + otros
                loss_savings_usd = (
                    annual_loss_savings_kwh
                    * self.a.losses_compensation_usd_per_kwh
                    * inflation_factor
                )
                capacity_usd = annual_capacity_savings_usd * inflation_factor
                other_usd = annual_other_revenue_usd * inflation_factor

                cf.revenue_savings_usd = loss_savings_usd + capacity_usd
                cf.revenue_other_usd = other_usd

            cf.net_usd = (
                cf.capex_usd
                + cf.opex_om_usd
                + cf.opex_losses_usd
                + cf.revenue_savings_usd
                + cf.revenue_other_usd
            )
            cashflows.append(cf)

        # Indicadores
        net_flows = [cf.net_usd for cf in cashflows]
        npv_value = npv(self.a.discount_rate, net_flows)
        irr_value = irr(net_flows)
        payback = payback_period(net_flows)

        # Beneficio/Costo: PV(ingresos) / PV(egresos)
        pv_revenues = sum(
            (cf.revenue_savings_usd + cf.revenue_other_usd)
            / (1.0 + self.a.discount_rate) ** cf.year
            for cf in cashflows
        )
        pv_costs = -sum(
            (cf.capex_usd + cf.opex_om_usd + cf.opex_losses_usd)
            / (1.0 + self.a.discount_rate) ** cf.year
            for cf in cashflows
        )
        bcr = pv_revenues / pv_costs if pv_costs > 0 else None

        if npv_value > 0:
            notes.append("VAN positivo: el proyecto crea valor.")
        else:
            notes.append("VAN negativo: revisar supuestos o alcance.")
        if irr_value is not None and irr_value > self.a.discount_rate:
            notes.append(
                f"TIR ({irr_value*100:.1f}%) supera la tasa de descuento "
                f"({self.a.discount_rate*100:.1f}%)."
            )

        return InvestmentResult(
            capex_total_usd=capex_total,
            cashflows=cashflows,
            npv_usd=npv_value,
            irr_pct=irr_value * 100.0 if irr_value is not None else None,
            payback_years=payback,
            benefit_cost_ratio=bcr,
            notes=notes,
        )
