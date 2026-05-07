# -*- coding: utf-8 -*-
"""Tests del módulo de inversión (engineering.investment)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.engineering import (
    CashFlow, InvestmentAnalyzer, InvestmentAssumptions, InvestmentResult,
    irr, npv, payback_period,
)


# =============================================================================
# Indicadores básicos
# =============================================================================
class TestNPV:

    def test_zero_rate_equals_sum(self):
        cfs = [-100, 30, 30, 30, 30]
        assert npv(0.0, cfs) == 20.0

    def test_positive_rate_reduces_present_value(self):
        cfs = [-100, 50, 50]
        v_low = npv(0.05, cfs)
        v_high = npv(0.20, cfs)
        # Tasa más alta → VAN más bajo (futuros valen menos)
        assert v_high < v_low

    def test_invalid_rate_raises(self):
        with pytest.raises(ValueError):
            npv(-1.5, [10, 20])


class TestIRR:

    def test_simple_irr(self):
        # Inversión 100, retornos 50/50/50 → IRR ~23%
        cfs = [-100, 50, 50, 50]
        rate = irr(cfs)
        assert rate is not None
        assert 0.20 <= rate <= 0.25
        # Verificación: NPV en la IRR debe ser ≈0
        assert abs(npv(rate, cfs)) < 1.0

    def test_no_sign_change_returns_none(self):
        # Todos positivos: no hay IRR válida
        rate = irr([10, 20, 30])
        assert rate is None

    def test_consistent_with_npv(self):
        cfs = [-200, 80, 90, 100]
        rate = irr(cfs)
        assert rate is not None
        assert abs(npv(rate, cfs)) < 1.0


class TestPayback:

    def test_simple_payback(self):
        # CAPEX 100, retornos uniformes 25/año → payback exacto = 4
        cfs = [-100, 25, 25, 25, 25, 25]
        pb = payback_period(cfs)
        assert pb == pytest.approx(4.0, abs=0.05)

    def test_no_recovery_returns_none(self):
        cfs = [-100, 10, 10, 10]
        assert payback_period(cfs) is None

    def test_interpolated_payback(self):
        # Payback entre año 2 y 3
        cfs = [-100, 30, 30, 80]
        pb = payback_period(cfs)
        assert pb is not None
        assert 2.0 < pb < 3.0


# =============================================================================
# CAPEX total
# =============================================================================
class TestCapex:

    def test_indirect_and_contingency_applied(self):
        a = InvestmentAnalyzer(InvestmentAssumptions(
            indirect_costs_pct=0.20, contingency_pct=0.10,
        ))
        # 100 × 1.20 × 1.10 = 132
        assert a.total_capex(100.0) == pytest.approx(132.0)

    def test_negative_capex_raises(self):
        a = InvestmentAnalyzer()
        with pytest.raises(ValueError):
            a.total_capex(-50)


# =============================================================================
# Análisis multianual completo
# =============================================================================
class TestAnalyze:

    def test_simple_5y_project_returns_result(self):
        # Proyecto que reduce pérdidas 50,000 kWh/año + difiere 20k USD/año
        a = InvestmentAnalyzer(InvestmentAssumptions(
            horizon_years=5,
            discount_rate=0.10,
            inflation_rate=0.0,
            indirect_costs_pct=0.0,
            contingency_pct=0.0,
            om_pct_of_capex_per_year=0.02,
        ))
        result = a.analyze(
            capex_direct_usd=200_000,
            annual_loss_savings_kwh=50_000,
            annual_capacity_savings_usd=20_000,
        )
        assert isinstance(result, InvestmentResult)
        assert result.capex_total_usd == 200_000
        assert len(result.cashflows) == 6   # años 0..5
        assert result.cashflows[0].capex_usd == -200_000
        assert result.cashflows[1].capex_usd == 0.0   # CAPEX solo en t=0

    def test_npv_calculated(self):
        # Horizonte 10 años, beneficios fuertes → VAN positivo
        a = InvestmentAnalyzer(InvestmentAssumptions(horizon_years=10))
        result = a.analyze(
            capex_direct_usd=100_000,
            annual_loss_savings_kwh=80_000,
            annual_capacity_savings_usd=20_000,
        )
        # Con horizonte largo y buenos beneficios el VAN debe ser positivo
        assert result.npv_usd > 0

    def test_negative_npv_when_no_savings(self):
        a = InvestmentAnalyzer()
        result = a.analyze(capex_direct_usd=100_000)
        # Sin ingresos, solo CAPEX y O&M → VAN negativo
        assert result.npv_usd < 0

    def test_payback_within_horizon(self):
        a = InvestmentAnalyzer(InvestmentAssumptions(
            horizon_years=10,
            indirect_costs_pct=0.0,
            contingency_pct=0.0,
            om_pct_of_capex_per_year=0.0,
            inflation_rate=0.0,
        ))
        # 100k inversión, ahorro 30k/año (de capacidad solamente) → payback ~3.3
        r = a.analyze(
            capex_direct_usd=100_000,
            annual_capacity_savings_usd=30_000,
        )
        assert r.payback_years is not None
        assert 3.0 < r.payback_years < 4.0

    def test_irr_above_discount_rate_for_good_project(self):
        a = InvestmentAnalyzer(InvestmentAssumptions(
            horizon_years=10,
            discount_rate=0.10,
            indirect_costs_pct=0.0,
            contingency_pct=0.0,
            om_pct_of_capex_per_year=0.0,
            inflation_rate=0.0,
        ))
        r = a.analyze(
            capex_direct_usd=100_000,
            annual_capacity_savings_usd=20_000,
        )
        assert r.irr_pct is not None
        assert r.irr_pct > 10.0   # supera la tasa de descuento

    def test_inflation_compounds_revenues(self):
        a_no_inf = InvestmentAnalyzer(InvestmentAssumptions(
            horizon_years=5, inflation_rate=0.0,
            indirect_costs_pct=0.0, contingency_pct=0.0,
            om_pct_of_capex_per_year=0.0,
        ))
        a_inf = InvestmentAnalyzer(InvestmentAssumptions(
            horizon_years=5, inflation_rate=0.05,
            indirect_costs_pct=0.0, contingency_pct=0.0,
            om_pct_of_capex_per_year=0.0,
        ))
        r0 = a_no_inf.analyze(capex_direct_usd=100_000,
                              annual_capacity_savings_usd=10_000)
        ri = a_inf.analyze(capex_direct_usd=100_000,
                           annual_capacity_savings_usd=10_000)
        # Con inflación, ingresos nominales crecen → más ingresos totales
        sum0 = sum(cf.revenue_savings_usd for cf in r0.cashflows)
        sumi = sum(cf.revenue_savings_usd for cf in ri.cashflows)
        assert sumi > sum0

    def test_cumulative_cashflow_monotonic_after_capex(self):
        a = InvestmentAnalyzer(InvestmentAssumptions(
            horizon_years=5, indirect_costs_pct=0.0, contingency_pct=0.0,
            om_pct_of_capex_per_year=0.0, inflation_rate=0.0,
        ))
        r = a.analyze(
            capex_direct_usd=100_000,
            annual_capacity_savings_usd=30_000,
        )
        cum = r.cumulative_cashflow()
        assert cum[0] == -100_000
        # Después de t=0, va aumentando
        for t in range(1, len(cum)):
            assert cum[t] > cum[t-1]

    def test_summary_lines_renderable(self):
        a = InvestmentAnalyzer()
        r = a.analyze(
            capex_direct_usd=50_000,
            annual_capacity_savings_usd=15_000,
        )
        lines = r.summary_lines()
        assert any("CAPEX inicial" in l for l in lines)
        assert any("VAN" in l for l in lines)


# =============================================================================
# CashFlow dataclass
# =============================================================================
class TestCashFlow:

    def test_default_zero_fields(self):
        cf = CashFlow(year=0)
        assert cf.capex_usd == 0
        assert cf.opex_om_usd == 0
        assert cf.net_usd == 0
