# -*- coding: utf-8 -*-
"""
Tests del módulo timeseries.

Cubre:
    - Generadores de perfiles (formas, cantidades, normalización)
    - Librería precargada Ecuador
    - Aplicación de escenarios a un Network
    - AnnualAggregator
    - TimeSeriesSolver (requiere opendssdirect)
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.timeseries import (
    HOURS_PER_DAY, HOURS_PER_YEAR,
    ProfileGenerator, ProfileLibrary,
    Scenario, ScenarioComparison,
    AnnualResults, BusAnnualStats, BranchAnnualStats,
)
from redes_engine.timeseries.aggregator import AnnualAggregator
from redes_engine.timeseries.profiles import (
    annual_energy_kwh, peak_demand_kw, load_factor,
)


# =============================================================================
# Generador de perfiles
# =============================================================================
class TestProfileGenerator:

    def test_constant_profile_length(self):
        gen = ProfileGenerator()
        p = gen.constant(value=2.5)
        assert len(p) == HOURS_PER_YEAR
        assert all(v == 2.5 for v in p)

    def test_residential_sierra_length(self):
        gen = ProfileGenerator(seed=1)
        p = gen.residential_sierra()
        assert len(p) == HOURS_PER_YEAR

    def test_residential_sierra_has_evening_peak(self):
        """El perfil residencial Sierra debe pico entre 18-22h."""
        gen = ProfileGenerator(seed=1)
        p = gen.residential_sierra(noise_pct=0.0)   # sin ruido para test
        # Promediar las primeras 7 días en cada hora
        avg_by_hour = [0.0] * 24
        for day in range(7):
            for h in range(24):
                avg_by_hour[h] += p[day * 24 + h]
        avg_by_hour = [v / 7.0 for v in avg_by_hour]
        # El pico debe estar entre 18 y 22
        peak_hour = avg_by_hour.index(max(avg_by_hour))
        assert 18 <= peak_hour <= 22

    def test_solar_pv_zero_at_night(self):
        """PV no genera entre 0-5 ni 19-23h."""
        gen = ProfileGenerator(seed=1)
        p = gen.solar_pv(sunrise_h=6, sunset_h=18, cloud_factor_std=0.0)
        # Muestra primer día
        for h in range(24):
            if h < 6 or h >= 18:
                assert p[h] == pytest.approx(0.0, abs=1e-6)

    def test_solar_pv_has_noon_peak(self):
        gen = ProfileGenerator(seed=1)
        p = gen.solar_pv(sunrise_h=6, sunset_h=18, cloud_factor_std=0.0,
                          seasonal_amplitude=0.0)
        # Pico de los primeros 24h debe estar al mediodía
        first_day = p[:24]
        peak_idx = first_day.index(max(first_day))
        assert 11 <= peak_idx <= 13

    def test_street_lighting_only_at_night(self):
        gen = ProfileGenerator()
        p = gen.street_lighting()
        for h in range(24):
            if 6 <= h < 18:
                assert p[h] == 0.0   # apagado de día
            else:
                assert p[h] > 0.0   # encendido de noche

    def test_industrial_24h_constant(self):
        gen = ProfileGenerator()
        p = gen.industrial(shift_hours=24, noise_pct=0.0)
        # Todos los valores cercanos al base (~0.92), salvo finde
        first_workday = p[:24]
        assert all(v == pytest.approx(0.92, abs=0.05) for v in first_workday)

    def test_ev_residential_charges_at_night(self):
        gen = ProfileGenerator(seed=42)
        p = gen.ev_residential(avg_arrival_hour=20, avg_kwh_per_day=22, rated_kw=7.4)
        # Sumar primeros 7 días por hora
        sum_by_hour = [0.0] * 24
        for day in range(30):   # mes
            for h in range(24):
                sum_by_hour[h] += p[day * 24 + h]
        # La energía total debe ocurrir mayormente en horas nocturnas (18-7)
        night_energy = sum(sum_by_hour[h] for h in range(18, 24)) + sum(
            sum_by_hour[h] for h in range(0, 8))
        day_energy = sum(sum_by_hour[h] for h in range(8, 18))
        assert night_energy > day_energy * 3   # ratio fuerte


# =============================================================================
# Librería de perfiles
# =============================================================================
class TestProfileLibrary:

    def test_ecuador_default_has_expected_profiles(self):
        lib = ProfileLibrary.ecuador_default()
        expected = {
            "residential_sierra", "residential_costa", "commercial",
            "industrial_24h", "industrial_8h", "street_lighting",
            "pv_sierra", "pv_costa", "pv_oriente",
            "ev_residential", "ev_dc_fast",
        }
        assert expected.issubset(set(lib.keys()))
        for name, profile in lib.items():
            assert len(profile) == HOURS_PER_YEAR, f"{name} ≠ 8760"


# =============================================================================
# Escenarios
# =============================================================================
class TestScenario:

    def test_scenario_load_growth(self):
        s = Scenario(name="2030", year=2030, base_year=2026,
                     base_load_growth_pct_per_year=3.0)
        # 4 años a 3% compuesto: 1.03^4 = 1.1255
        assert s.base_load_factor == pytest.approx(1.1255, abs=1e-3)

    def test_scenario_zero_growth_when_same_year(self):
        s = Scenario(name="X", year=2026, base_year=2026,
                     base_load_growth_pct_per_year=5.0)
        assert s.base_load_factor == 1.0
        assert s.years_from_base == 0

    def test_apply_scenario_adds_evs(self):
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        net = build_urbanizacion_pastaza()
        n_residential = sum(
            1 for a in net.assets.values()
            if a.asset_type.value == "load_residencial"
        )
        scenario = Scenario(
            name="100% VE", year=2030,
            ev_penetration_pct=100.0,
        )
        profiles = ProfileLibrary.ecuador_default()
        application = scenario.apply_to_network(net, profiles, random_seed=1)
        # Debe haber añadido EV en cada medidor residencial
        # (algunos pueden ya tener EV por nombre pero el factory crea único ID)
        assert len(application.added_evs) == n_residential


# =============================================================================
# Agregador
# =============================================================================
class TestAggregator:

    def _mock_hourly_result(
        self, demand_kw=10, losses_kw=0.5,
        bus_v_pu=0.98, branch_loading_pct=50,
    ):
        from redes_engine.core.results import (
            BranchFlowResult, BusVoltageResult,
            ComplianceStatus, PowerFlowResult,
        )
        result = PowerFlowResult(
            converged=True, iterations=1,
            total_power_kw=demand_kw, total_losses_kw=losses_kw,
        )
        # 1 bus
        v_drop = (1.0 - bus_v_pu) * 100
        compl = (ComplianceStatus.VIOLATION if abs(v_drop) > 8.0
                 else ComplianceStatus.WARNING if abs(v_drop) > 6.4
                 else ComplianceStatus.OK)
        result.bus_voltages["B1"] = BusVoltageResult(
            bus_id="B1", v_magnitude_kv=0.220 * bus_v_pu,
            v_pu=bus_v_pu, v_drop_pct=v_drop,
            angle_deg=0, voltage_nominal_kv=0.220,
            compliance=compl,
        )
        # 1 branch
        ovl = (ComplianceStatus.VIOLATION if branch_loading_pct > 100
               else ComplianceStatus.WARNING if branch_loading_pct > 80
               else ComplianceStatus.OK)
        result.branch_flows["L1"] = BranchFlowResult(
            branch_id="L1", p_kw=demand_kw, q_kvar=2, s_kva=demand_kw,
            current_a=20, rated_a=100,
            loading_pct=branch_loading_pct,
            losses_kw=0.05, losses_kvar=0.02,
            compliance=ovl,
        )
        return result

    def test_aggregator_accumulates(self):
        agg = AnnualAggregator()
        for h in range(10):
            agg.update(h, self._mock_hourly_result(demand_kw=10 + h))
        result = agg.finalize("Test")
        assert result.n_hours_simulated == 10
        # Energía servida: 10+11+...+19 = 145 kW·h → 0.145 MWh
        assert result.total_energy_served_mwh == pytest.approx(0.145)
        assert result.peak_demand_kw == 19
        assert result.peak_demand_hour == 9

    def test_aggregator_counts_violations(self):
        agg = AnnualAggregator()
        # 3 horas con violación, 5 normales
        for h in range(3):
            agg.update(h, self._mock_hourly_result(bus_v_pu=0.85))   # ΔV=15% violación
        for h in range(3, 8):
            agg.update(h, self._mock_hourly_result(bus_v_pu=0.99))   # OK
        result = agg.finalize()
        assert "B1" in result.bus_stats
        assert result.bus_stats["B1"].hours_in_violation == 3


# =============================================================================
# Utilidades de perfiles
# =============================================================================
class TestProfileUtils:

    def test_annual_energy_kwh(self):
        # Perfil constante 0.5 con rated 10 kW × 8760h = 43800 kWh
        profile = [0.5] * HOURS_PER_YEAR
        assert annual_energy_kwh(profile, 10.0) == pytest.approx(43800)

    def test_load_factor_constant_is_one(self):
        profile = [0.7] * HOURS_PER_YEAR
        assert load_factor(profile) == pytest.approx(1.0)

    def test_load_factor_pulse_low(self):
        # Perfil 1.0 en 1 hora, 0 en 23 horas (factor de carga = 1/24)
        profile = [1.0] + [0.0] * 23
        # Repetimos pattern 365 veces
        profile = profile * 365
        assert load_factor(profile) == pytest.approx(1/24, abs=1e-4)


# =============================================================================
# Solver (requiere OpenDSS)
# =============================================================================
opendss = pytest.importorskip(
    "opendssdirect", reason="opendssdirect no instalado",
)


class TestTimeSeriesSolver:

    @pytest.fixture
    def small_net(self):
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        return build_urbanizacion_pastaza()

    def test_solver_runs_short_horizon(self, small_net):
        from redes_engine.timeseries import TimeSeriesSolver

        solver = TimeSeriesSolver(small_net)
        annual = solver.run(hours=24, scenario_name="Smoke")
        assert annual.n_hours_simulated > 0
        assert annual.total_energy_served_mwh >= 0

    def test_solver_collects_bus_stats(self, small_net):
        from redes_engine.timeseries import TimeSeriesSolver

        solver = TimeSeriesSolver(small_net)
        annual = solver.run(hours=48, scenario_name="Test")
        assert len(annual.bus_stats) > 0
        # Cada bus debe tener algún rango de voltaje
        for stats in annual.bus_stats.values():
            assert stats.v_pu_min <= stats.v_pu_max

    def test_solver_with_scenario(self, small_net):
        """Aplicar escenario y simular."""
        from redes_engine.timeseries import (
            ProfileLibrary, Scenario, TimeSeriesSolver,
        )
        profiles = ProfileLibrary.ecuador_default()
        scenario = Scenario(
            name="50% VE", year=2030,
            ev_penetration_pct=50.0,
            pv_penetration_pct=0.0,
            base_load_growth_pct_per_year=3.0,
        )
        scenario.apply_to_network(small_net, profiles, random_seed=42)

        solver = TimeSeriesSolver(small_net, profiles=profiles)
        annual = solver.run(hours=24, scenario_name=scenario.name)
        assert annual.n_hours_simulated == 24
