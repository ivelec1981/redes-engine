# -*- coding: utf-8 -*-
"""Tests del módulo redes_engine.engineering (cálculos clásicos migrados)."""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.engineering import (
    AmpacityResult,
    BOMItem,
    BudgetEngine,
    CableConfig,
    ConductorProperties,
    CurveType,
    FaultCalculation,
    MechanicalState,
    ProtectionDevice,
    SagResult,
    UPItem,
    coordinate_curves,
    compute_ampacity_underground,
    compute_max_tension,
    compute_sag,
    derate_for_temperature,
    fault_current_3phase,
    fault_current_phase_to_ground,
    select_fuse_for_load,
    solve_change_of_state,
)


# =============================================================================
# MECHANICAL
# =============================================================================
@pytest.fixture
def acsr_4_0() -> ConductorProperties:
    """ACSR 4/0 Penguin — conductor típico de MT distribución Ecuador."""
    return ConductorProperties(
        name="ACSR_4/0AWG_Penguin",
        section_mm2=107.0,
        diameter_mm=13.26,
        weight_kg_m=0.475,
        rated_strength_kN=37.36,
        elastic_modulus_GPa=68.9,
        thermal_expansion_coef=1.93e-5,
        max_tension_pct=0.20,
    )


class TestMechanical:

    def test_max_tension(self, acsr_4_0):
        T_max = compute_max_tension(acsr_4_0)
        # 20% de 37360 N = 7472 N
        assert T_max == pytest.approx(7472.0, rel=0.01)

    def test_sag_parabolic_simple(self, acsr_4_0):
        state = MechanicalState(
            span_m=80.0, temperature_c=20.0, tension_n=5000.0,
        )
        result = compute_sag(acsr_4_0, state, use_parabolic=True)
        # f = wL²/(8T) ; w = 0.475·9.81 = 4.66 N/m
        # f = 4.66·80²/(8·5000) = 0.745 m
        assert 0.6 <= result.sag_m <= 0.85
        assert result.tension_at_low_point_n == pytest.approx(5000.0)

    def test_sag_catenary_consistent_with_parabolic_short_span(self, acsr_4_0):
        # Para vanos cortos, catenaria ≈ parábola
        state = MechanicalState(
            span_m=80.0, temperature_c=20.0, tension_n=5000.0,
        )
        sag_parabolic = compute_sag(acsr_4_0, state, use_parabolic=True).sag_m
        sag_catenary = compute_sag(acsr_4_0, state, use_parabolic=False).sag_m
        # Diferencia <5% para vano corto
        assert abs(sag_catenary - sag_parabolic) / sag_parabolic < 0.05

    def test_change_of_state_consistent(self, acsr_4_0):
        # Estado inicial: T1=8000 N a 0°C (frío)
        state1 = MechanicalState(
            span_m=80.0, temperature_c=0.0, tension_n=8000.0,
        )
        # Estado final: 50°C — conductor se dilata, tensión baja
        state2 = MechanicalState(
            span_m=80.0, temperature_c=50.0,
        )
        T2 = solve_change_of_state(acsr_4_0, state1, state2)
        # Tensión positiva
        assert T2 > 0
        # Con más temperatura, debe relajarse algo
        assert T2 <= state1.tension_n * 1.05   # tolerancia por iteración numérica

    def test_change_of_state_with_wind(self, acsr_4_0):
        state1 = MechanicalState(
            span_m=80.0, temperature_c=20.0, tension_n=5000.0,
        )
        # Estado con viento alto: tensión debe AUMENTAR
        state2 = MechanicalState(
            span_m=80.0, temperature_c=20.0,
            wind_pressure_pa=400.0,
        )
        T2 = solve_change_of_state(acsr_4_0, state1, state2)
        assert T2 > state1.tension_n


# =============================================================================
# PROTECTIONS
# =============================================================================
class TestProtections:

    def test_fault_3phase(self):
        result = fault_current_3phase(voltage_kv=22.8, impedance_pu=0.05)
        assert isinstance(result, FaultCalculation)
        assert result.fault_type == "3-phase"
        # I_3φ = V_LL/(√3·Z); con z_pu=0.05, base 100 MVA, V=22.8 kV
        # → ~50.6 kA (cortocircuito típico cerca de fuente fuerte)
        assert 30.0 <= result.current_ka <= 100.0

    def test_fault_phase_ground(self):
        result = fault_current_phase_to_ground(
            voltage_kv=22.8, z1_pu=0.05, z2_pu=0.05, z0_pu=0.10,
        )
        assert result.fault_type == "phase-ground"
        assert result.current_ka > 0

    def test_select_fuse_normal_load(self):
        # 75 kVA en 22.8 kV → ~1.9 A nominal
        # × 1.4 = 2.66 A → fusible 3A
        device = select_fuse_for_load(load_kva=75, voltage_kv=22.8)
        assert device.is_fuse
        assert device.rated_a >= 2.66

    def test_select_fuse_high_load(self):
        device = select_fuse_for_load(load_kva=2000, voltage_kv=22.8)
        # 2000/(√3·22.8) ≈ 50.6 A; ×1.4 = 70.8 A → fusible 80A
        assert device.rated_a >= 70.0

    def test_iec_curve_inverse(self):
        from redes_engine.engineering.protections import operating_time
        # Multiplicador alto → tiempo corto
        t_high = operating_time(CurveType.INVERSE_NORMAL, 1000, 100, tms=0.1)
        t_low = operating_time(CurveType.INVERSE_NORMAL, 200, 100, tms=0.1)
        assert t_high < t_low   # más corriente = menor tiempo

    def test_curve_below_pickup_does_not_operate(self):
        from redes_engine.engineering.protections import operating_time
        # Si I < pickup, no opera (tiempo = inf)
        t = operating_time(CurveType.INVERSE_NORMAL, 50, 100, tms=0.1)
        assert t == float("inf")

    def test_coordination_with_margin(self):
        primary = ProtectionDevice(
            name="primary", rated_a=100, breaking_ka=8,
            curve=CurveType.INVERSE_NORMAL, tms=0.1, pickup_a=100,
        )
        backup = ProtectionDevice(
            name="backup", rated_a=200, breaking_ka=8,
            curve=CurveType.INVERSE_NORMAL, tms=0.3, pickup_a=200,
        )
        results = coordinate_curves(primary, backup, [500, 1000], margin_s=0.3)
        assert len(results) == 2
        for I, ok, msg in results:
            assert isinstance(I, (int, float))
            assert isinstance(ok, bool)


# =============================================================================
# AMPACITY
# =============================================================================
class TestAmpacity:

    def test_no_derate_at_nominal_conditions(self):
        cfg = CableConfig(
            cable_name="AL_1/0_XLPE",
            rated_ampacity_a=200,
            n_circuits_in_duct_bank=1,
            burial_depth_m=1.0,
            soil_thermal_resistivity_km_per_w=1.0,
        )
        result = compute_ampacity_underground(cfg, soil_temp_c=20.0)
        # En condiciones nominales: derate = 1.0
        assert result.total_derate_factor == pytest.approx(1.0, rel=0.01)
        assert result.final_ampacity_a == pytest.approx(200, rel=0.01)

    def test_derate_for_grouping(self):
        cfg_single = CableConfig(
            cable_name="X", rated_ampacity_a=200,
            n_circuits_in_duct_bank=1,
        )
        cfg_grouped = CableConfig(
            cable_name="X", rated_ampacity_a=200,
            n_circuits_in_duct_bank=4,
        )
        r1 = compute_ampacity_underground(cfg_single)
        r4 = compute_ampacity_underground(cfg_grouped)
        # 4 cables agrupados → derate ~0.74
        assert r4.final_ampacity_a < r1.final_ampacity_a
        assert r4.derate_factor_grouping == pytest.approx(0.74, rel=0.01)

    def test_derate_for_high_temp(self):
        result = derate_for_temperature(
            soil_temp_c=40.0, cable_max_temp_c=90.0, rated_soil_temp_c=20.0,
        )
        # 40°C suelo → menos margen térmico → factor < 1
        assert 0.7 < result < 1.0

    def test_high_resistivity_reduces_ampacity(self):
        cfg = CableConfig(
            cable_name="X", rated_ampacity_a=200,
            soil_thermal_resistivity_km_per_w=2.5,   # suelo seco
        )
        r = compute_ampacity_underground(cfg)
        assert r.final_ampacity_a < 200


# =============================================================================
# BUDGET
# =============================================================================
class TestBudget:

    def test_simple_explosion_with_recipes(self):
        uc_db = {
            "PSC-12500": {
                "description": "Poste hormigón 12m/500kg",
                "materials": [
                    {"item": "01001", "descripcion": "Poste", "unidad": "u", "cantidad": 1},
                    {"item": "02005", "descripcion": "Tornillo cabeza", "unidad": "u", "cantidad": 8},
                ],
            },
        }
        prices = {"01001": 250.0, "02005": 1.50}
        engine = BudgetEngine(uc_db, prices)
        bom = engine.compute_bom([UPItem(code="PSC-12500", quantity=2)])

        # Postes: 2 × $250 = 500
        # Tornillos: 16 × $1.50 = 24
        assert bom.total_cost == pytest.approx(524.0)
        assert bom.n_items_unique == 2

    def test_unknown_up_treated_as_generic_item(self):
        engine = BudgetEngine({}, {"DESCONOCIDO": 100.0})
        bom = engine.compute_bom([
            UPItem(code="DESCONOCIDO", quantity=3, description="Item generico"),
        ])
        # Sin receta, se trata como item generico
        assert bom.n_ups_processed == 3

    def test_aggregation_across_multiple_ups(self):
        uc_db = {
            "POSTE_A": {"materials": [{"item": "X1", "descripcion": "X", "unidad": "u", "cantidad": 1}]},
            "POSTE_B": {"materials": [{"item": "X1", "descripcion": "X", "unidad": "u", "cantidad": 2}]},
        }
        engine = BudgetEngine(uc_db, {"X1": 10.0})
        bom = engine.compute_bom([
            UPItem(code="POSTE_A", quantity=5),  # → 5 × X1
            UPItem(code="POSTE_B", quantity=3),  # → 6 × X1
        ])
        # X1 agregado: 5+6 = 11 unidades, ×$10 = $110
        assert bom.items["X1"].quantity == 11
        assert bom.total_cost == pytest.approx(110.0)
