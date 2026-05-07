# -*- coding: utf-8 -*-
"""
Tests del módulo timeseries.dispatch — estrategias de despacho BESS.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.timeseries.dispatch import (
    BESSState, MILPDailyDispatch, PeakShavingDispatch,
    StaticDispatch, build_bess_states, create_dispatcher,
)


# =============================================================================
# BESSState
# =============================================================================
class TestBESSState:

    def test_initial(self):
        s = BESSState(asset_id="B", capacity_kwh=10.0, rated_kw=5.0, soc=0.5)
        assert s.soc == 0.5
        assert s.last_action_kw == 0.0

    def test_can_charge_limited_by_rated(self):
        s = BESSState(asset_id="B", capacity_kwh=100.0, rated_kw=5.0, soc=0.0)
        # SoC bajo → puede absorber mucha energía, pero limitado por rated_kw
        assert s.can_charge_kw() == pytest.approx(5.0)

    def test_can_charge_limited_by_soc(self):
        s = BESSState(asset_id="B", capacity_kwh=10.0, rated_kw=100.0,
                      soc=0.93, soc_max=0.95)
        # Solo cabe (0.95-0.93) * 10 / 0.95 = 0.21 kWh
        assert s.can_charge_kw() < 1.0

    def test_can_discharge_at_soc_min(self):
        s = BESSState(asset_id="B", capacity_kwh=10, rated_kw=5, soc=0.20)
        assert s.can_discharge_kw() == pytest.approx(0.0)

    def test_apply_charge_increases_soc(self):
        s = BESSState(asset_id="B", capacity_kwh=10.0, rated_kw=5.0, soc=0.5)
        s.apply_action(5.0)   # carga 5 kW por 1 h
        # Energía absorbida: 5 * 0.95 = 4.75 kWh / 10 = 0.475 → soc=0.975 → cap a 0.95
        assert s.soc == 0.95
        assert s.last_action_kw == 5.0

    def test_apply_discharge_decreases_soc(self):
        s = BESSState(asset_id="B", capacity_kwh=10.0, rated_kw=5.0, soc=0.8)
        s.apply_action(-5.0)   # descarga 5 kW por 1 h
        assert s.soc < 0.8


# =============================================================================
# Strategies
# =============================================================================
class TestStaticDispatch:

    def test_returns_last_action(self):
        d = StaticDispatch()
        s = BESSState(asset_id="B", capacity_kwh=10, rated_kw=5, soc=0.5,
                      last_action_kw=2.5)
        out = d.get_bess_power_kw(
            hour=10, bess_state=s,
            net_demand_kw=10, pv_generation_kw=2,
            transformer_loading_pct=70,
        )
        assert out == 2.5


class TestPeakShavingDispatch:

    def test_discharges_when_trafo_overloaded(self):
        d = PeakShavingDispatch(peak_threshold_pct=80)
        s = BESSState(asset_id="B", capacity_kwh=20, rated_kw=10, soc=0.7)
        out = d.get_bess_power_kw(
            hour=20, bess_state=s,
            net_demand_kw=80, pv_generation_kw=0,
            transformer_loading_pct=95,
        )
        # Debe descargar (signo negativo)
        assert out < 0

    def test_charges_with_pv_surplus(self):
        d = PeakShavingDispatch()
        s = BESSState(asset_id="B", capacity_kwh=20, rated_kw=10, soc=0.5)
        out = d.get_bess_power_kw(
            hour=12, bess_state=s,
            net_demand_kw=2, pv_generation_kw=15,
            transformer_loading_pct=20,
        )
        # PV surplus = 13 kW → carga (positivo)
        assert out > 0

    def test_charges_at_low_tariff_hours(self):
        d = PeakShavingDispatch(low_tariff_hours=[2, 3, 4])
        s = BESSState(asset_id="B", capacity_kwh=20, rated_kw=10, soc=0.4)
        out = d.get_bess_power_kw(
            hour=3, bess_state=s,
            net_demand_kw=5, pv_generation_kw=0,
            transformer_loading_pct=15,
        )
        # En hora valle con SoC<70% y trafo bajo → carga moderada
        assert out > 0

    def test_idle_in_normal_conditions(self):
        d = PeakShavingDispatch()
        s = BESSState(asset_id="B", capacity_kwh=20, rated_kw=10, soc=0.6)
        out = d.get_bess_power_kw(
            hour=14, bess_state=s,
            net_demand_kw=10, pv_generation_kw=2,
            transformer_loading_pct=60,
        )
        # Trafo medio, sin sobrante PV, no es hora valle → idle
        assert out == 0.0


class TestFactory:

    def test_create_static(self):
        d = create_dispatcher("static")
        assert isinstance(d, StaticDispatch)

    def test_create_peak_shaving(self):
        d = create_dispatcher("peak_shaving")
        assert isinstance(d, PeakShavingDispatch)

    def test_create_peak_shaving_with_kwargs(self):
        d = create_dispatcher("peak_shaving", peak_threshold_pct=70.0)
        assert isinstance(d, PeakShavingDispatch)
        assert d.peak_threshold == 70.0

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="desconocido"):
            create_dispatcher("magic_strategy")


# =============================================================================
# build_bess_states
# =============================================================================
class TestBuildBessStates:

    def test_extracts_storage_only(self):
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        net = build_urbanizacion_pastaza()
        states = build_bess_states(net)
        # La red tiene 3 BESS (BS_010, V2G_011, BESS_006)
        assert len(states) >= 2
        for s in states.values():
            assert s.capacity_kwh > 0
            assert s.rated_kw > 0


# =============================================================================
# Integración: solver con peak_shaving (requiere OpenDSS)
# =============================================================================
opendss = pytest.importorskip(
    "opendssdirect", reason="opendssdirect no instalado",
)


class TestSolverWithDispatch:

    def test_peak_shaving_reduces_trafo_loading(self):
        """Validación crítica: peak-shaving reduce el pico del trafo vs static."""
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        from redes_engine.timeseries import (
            ProfileLibrary, Scenario, TimeSeriesSolver,
        )

        profiles = ProfileLibrary.ecuador_default(seed=42)

        # Caso estresado: 50% VE en 2030
        def _build_stressed():
            n = build_urbanizacion_pastaza()
            Scenario(name="X", year=2030, base_year=2026,
                     ev_penetration_pct=50.0,
                     base_load_growth_pct_per_year=3.0
            ).apply_to_network(n, profiles, random_seed=42)
            return n

        # Static
        net_a = _build_stressed()
        annual_static = TimeSeriesSolver(
            net_a, profiles=profiles, dispatch_mode="static",
        ).run(hours=168, scenario_name="static")

        # Peak shaving
        net_b = _build_stressed()
        annual_peak = TimeSeriesSolver(
            net_b, profiles=profiles, dispatch_mode="peak_shaving",
        ).run(hours=168, scenario_name="peak_shaving")

        # peak_shaving DEBE reducir el trafo pico
        assert (annual_peak.peak_transformer_loading_pct
                < annual_static.peak_transformer_loading_pct), (
            f"Esperaba reducción: static={annual_static.peak_transformer_loading_pct}% "
            f"vs peak={annual_peak.peak_transformer_loading_pct}%"
        )
