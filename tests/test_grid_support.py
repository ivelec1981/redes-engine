# -*- coding: utf-8 -*-
"""
Tests del modo GRID_SUPPORT (regulación V/f IEEE 1547-2018).

Verifica:
    - Volt-Watt: limita descarga cuando V está alta
    - Volt-Var: inyecta Q cuando V baja, absorbe Q cuando V alta
    - Freq-Watt: descarga si f baja, carga si f alta
    - Prioridad: frecuencia > voltaje > peak-shaving
    - Validaciones de rangos físicos
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.timeseries.dispatch import (
    BESSState, GridSupportDispatch, create_dispatcher,
)


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def bess_at_50pct():
    """BESS de 50 kW / 100 kWh con SOC=50%."""
    return BESSState(
        asset_id="BESS1",
        capacity_kwh=100.0,
        rated_kw=50.0,
        soc=0.50,
    )


@pytest.fixture
def gs():
    """GridSupportDispatch con valores default."""
    return GridSupportDispatch()


# =============================================================================
# Volt-Watt
# =============================================================================
class TestVoltWatt:

    def test_normal_voltage_no_restriction(self, gs):
        # V=1.00 → factor=1.0 (sin limitación)
        assert gs._volt_watt_factor(1.00) == pytest.approx(1.0)

    def test_high_voltage_limits_discharge(self, gs):
        # V=1.075 (medio camino entre 1.05 y 1.10) → factor=0.5
        assert gs._volt_watt_factor(1.075) == pytest.approx(0.5)

    def test_very_high_voltage_blocks_discharge(self, gs):
        # V≥1.10 → factor=0.0
        assert gs._volt_watt_factor(1.10) == pytest.approx(0.0)
        assert gs._volt_watt_factor(1.15) == pytest.approx(0.0)

    def test_below_threshold_unrestricted(self, gs):
        assert gs._volt_watt_factor(0.95) == pytest.approx(1.0)
        assert gs._volt_watt_factor(1.04) == pytest.approx(1.0)


# =============================================================================
# Volt-Var
# =============================================================================
class TestVoltVar:

    def test_inside_deadband_no_q(self, gs):
        # V dentro de [0.97, 1.03] → Q=0
        assert gs._volt_var_kvar(1.00, q_max_kvar=20.0) == 0.0
        assert gs._volt_var_kvar(0.99, q_max_kvar=20.0) == 0.0
        assert gs._volt_var_kvar(1.02, q_max_kvar=20.0) == 0.0

    def test_high_voltage_absorbs_q(self, gs):
        # V > 1.03 → Q negativo (absorbe)
        q = gs._volt_var_kvar(1.05, q_max_kvar=20.0)
        assert q < 0
        # V=1.10 → Q absorbe el máximo
        q_max_neg = gs._volt_var_kvar(1.10, q_max_kvar=20.0)
        assert q_max_neg == pytest.approx(-20.0)

    def test_low_voltage_injects_q(self, gs):
        # V < 0.97 → Q positivo (inyecta)
        q = gs._volt_var_kvar(0.95, q_max_kvar=20.0)
        assert q > 0
        # V=0.90 → Q inyecta el máximo
        q_max_pos = gs._volt_var_kvar(0.90, q_max_kvar=20.0)
        assert q_max_pos == pytest.approx(20.0)

    def test_q_clamped_below_v_min(self, gs):
        # V por debajo del mínimo: no excede Q_max
        q = gs._volt_var_kvar(0.85, q_max_kvar=20.0)
        assert abs(q) <= 20.0

    def test_get_bess_kvar_uses_v_pu_from_context(self, gs, bess_at_50pct):
        # V alta → Q absorbe (signo negativo)
        q_high = gs.get_bess_kvar(0, bess_at_50pct, v_pu=1.08)
        assert q_high < 0
        # V baja → Q inyecta
        q_low = gs.get_bess_kvar(0, bess_at_50pct, v_pu=0.93)
        assert q_low > 0
        # V nominal → Q=0
        q_nom = gs.get_bess_kvar(0, bess_at_50pct, v_pu=1.00)
        assert q_nom == 0.0


# =============================================================================
# Freq-Watt
# =============================================================================
class TestFreqWatt:

    def test_in_band_returns_none(self, gs):
        assert gs._freq_watt_kw(60.0, p_max_kw=50.0) is None
        assert gs._freq_watt_kw(60.3, p_max_kw=50.0) is None

    def test_low_freq_discharges(self, gs):
        # f<59.5 → P negativa (descarga)
        p = gs._freq_watt_kw(59.0, p_max_kw=50.0)
        assert p < 0

    def test_high_freq_charges(self, gs):
        # f>60.5 → P positiva (carga)
        p = gs._freq_watt_kw(61.0, p_max_kw=50.0)
        assert p > 0

    def test_freq_response_dominates_voltage(self, gs, bess_at_50pct):
        """Si frecuencia está fuera de banda, manda sobre V."""
        # f baja + V alta: la frecuencia gana, BESS descarga
        p = gs.get_bess_power_kw(
            hour=12, bess_state=bess_at_50pct,
            net_demand_kw=10, pv_generation_kw=0,
            transformer_loading_pct=50,
            v_pu=1.08,        # tensión alta (Volt-Watt querría restringir)
            freq_hz=59.0,     # pero la frecuencia baja exige descarga
        )
        assert p < 0   # descarga (apoya frecuencia)


# =============================================================================
# Combinación de modos
# =============================================================================
class TestCombinedBehavior:

    def test_high_voltage_clips_peak_shaving(self, gs, bess_at_50pct):
        """Volt-Watt limita la descarga aunque haya pico de carga."""
        # Trafo cargado 90% → peak-shaving querría descargar
        # pero V=1.08 (factor=0.4) reduce la descarga
        p = gs.get_bess_power_kw(
            hour=20, bess_state=bess_at_50pct,
            net_demand_kw=80, pv_generation_kw=0,
            transformer_loading_pct=90,
            v_pu=1.08,        # alta → Volt-Watt activa
            freq_hz=60.0,
        )
        # Es descarga, pero menor que sin limitación V-W
        assert p < 0

        p_normal_v = gs.get_bess_power_kw(
            hour=20, bess_state=bess_at_50pct,
            net_demand_kw=80, pv_generation_kw=0,
            transformer_loading_pct=90,
            v_pu=1.00,
            freq_hz=60.0,
        )
        assert abs(p) < abs(p_normal_v)

    def test_low_voltage_triggers_discharge(self, gs, bess_at_50pct):
        """V muy baja debe forzar descarga para subir tensión."""
        p = gs.get_bess_power_kw(
            hour=20, bess_state=bess_at_50pct,
            net_demand_kw=10, pv_generation_kw=0,
            transformer_loading_pct=50,
            v_pu=0.93,        # baja
            freq_hz=60.0,
        )
        assert p < 0   # descarga

    def test_pv_surplus_charges_when_v_is_normal(self, gs):
        """Sobrante PV → carga si V no está alta."""
        bess = BESSState(
            asset_id="B", capacity_kwh=100, rated_kw=50, soc=0.30,
        )
        p = gs.get_bess_power_kw(
            hour=12, bess_state=bess,
            net_demand_kw=5, pv_generation_kw=20,   # sobrante 15 kW
            transformer_loading_pct=20,
            v_pu=1.00,
            freq_hz=60.0,
        )
        assert p > 0   # carga

    def test_default_context_uses_nominal_values(self, gs, bess_at_50pct):
        """Si no se pasa v_pu/freq, asume nominales (1.0 / 60.0)."""
        # Sin contexto explícito, se comporta como peak-shaving normal
        p = gs.get_bess_power_kw(
            hour=20, bess_state=bess_at_50pct,
            net_demand_kw=80, pv_generation_kw=0,
            transformer_loading_pct=90,
        )
        assert p < 0   # descarga normal


# =============================================================================
# Factory
# =============================================================================
class TestFactory:

    def test_create_grid_support(self):
        d = create_dispatcher("grid_support")
        assert isinstance(d, GridSupportDispatch)

    def test_create_grid_support_alias(self):
        for alias in ("grid-support", "v_f", "vf"):
            assert isinstance(create_dispatcher(alias), GridSupportDispatch)

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="desconocido"):
            create_dispatcher("foo_mode")


# =============================================================================
# Validaciones del constructor
# =============================================================================
class TestValidation:

    def test_invalid_volt_var_band_raises(self):
        with pytest.raises(ValueError, match="Volt-Var"):
            GridSupportDispatch(v_var_low=1.05, v_var_high=0.95)   # invertido

    def test_invalid_volt_watt_band_raises(self):
        with pytest.raises(ValueError, match="Volt-Watt"):
            GridSupportDispatch(v_watt_low=1.10, v_watt_high=1.05)

    def test_invalid_freq_band_raises(self):
        with pytest.raises(ValueError, match="frecuencia"):
            GridSupportDispatch(f_low_hz=60.5, f_nominal_hz=60.0, f_high_hz=59.5)


# =============================================================================
# Integración con el solver — el bug huérfano que esto previene
# =============================================================================
class TestSolverIntegration:
    """
    Verifica que GridSupportDispatch recibe la tensión REAL del bus desde el
    solver (paso predictor-corrector) y no el default nominal. Antes del fix,
    el solver nunca pasaba v_pu ni llamaba get_bess_kvar, así que grid_support
    degeneraba en peak_shaving en cualquier corrida 8760h.
    """

    def test_solver_feeds_real_voltage_to_dispatcher(self):
        pytest.importorskip("opendssdirect", reason="OpenDSS no instalado")
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        from redes_engine.timeseries import ProfileLibrary, TimeSeriesSolver

        class SpyGridSupport(GridSupportDispatch):
            def __init__(self):
                super().__init__()
                self.seen_vpu = []
                self.kvar_called = 0

            def get_bess_power_kw(self, hour, bess_state, net_demand_kw,
                                   pv_generation_kw, transformer_loading_pct,
                                   **context):
                self.seen_vpu.append(context.get("v_pu"))
                return super().get_bess_power_kw(
                    hour, bess_state, net_demand_kw, pv_generation_kw,
                    transformer_loading_pct, **context,
                )

            def get_bess_kvar(self, hour, bess_state, **context):
                self.kvar_called += 1
                return super().get_bess_kvar(hour, bess_state, **context)

        profiles = ProfileLibrary.ecuador_default(seed=42)
        net = build_urbanizacion_pastaza()
        solver = TimeSeriesSolver(
            net, profiles=profiles, dispatch_mode="grid_support",
        )
        spy = SpyGridSupport()
        solver.dispatcher = spy          # inyectar el spy antes de run()
        solver.run(hours=24, scenario_name="grid_support")

        # Debe haberse invocado el despacho con contexto de tensión
        assert spy.seen_vpu, "El dispatcher nunca fue invocado"
        # Y al menos una lectura debe ser tensión REAL (≠ default nominal 1.0)
        real_readings = [v for v in spy.seen_vpu if v is not None and abs(v - 1.0) > 1e-6]
        assert real_readings, (
            "El solver nunca pasó v_pu real al dispatcher "
            "(grid_support seguiría huérfano)"
        )
        # Y la reactiva Volt-Var debe haberse consultado
        assert spy.kvar_called > 0, "get_bess_kvar nunca se invocó"

    def test_grid_support_runs_end_to_end(self):
        pytest.importorskip("opendssdirect", reason="OpenDSS no instalado")
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        from redes_engine.timeseries import ProfileLibrary, TimeSeriesSolver

        profiles = ProfileLibrary.ecuador_default(seed=42)
        net = build_urbanizacion_pastaza()
        annual = TimeSeriesSolver(
            net, profiles=profiles, dispatch_mode="grid_support",
        ).run(hours=48, scenario_name="grid_support")
        # La corrida completa debe producir resultados válidos
        assert annual.n_hours_simulated > 0
