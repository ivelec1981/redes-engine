# -*- coding: utf-8 -*-
"""Tests del módulo engineering.substation."""

import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.engineering import (
    FeederBay, PowerTransformer, Substation, SubstationStatus,
    SubstationTopology, detect_substations, select_transformer_for_load,
)


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def trafo_10mva():
    return PowerTransformer(
        name="T1",
        rated_mva=10.0,
        rated_mva_onaf=12.5,
        voltage_at_kv=69.0,
        voltage_mt_kv=22.8,
        impedance_pct=8.0,
    )


@pytest.fixture
def trafo_15mva():
    return PowerTransformer(
        name="T2",
        rated_mva=15.0,
        rated_mva_onaf=18.0,
        impedance_pct=8.5,
    )


@pytest.fixture
def feeder_4mw():
    return FeederBay(
        name="F1", voltage_kv=22.8, rated_a=600,
        expected_load_mw=4.0, expected_load_mvar=1.5,
    )


@pytest.fixture
def feeder_5mw():
    return FeederBay(
        name="F2", voltage_kv=22.8, rated_a=600,
        expected_load_mw=5.0, expected_load_mvar=2.0,
    )


# =============================================================================
# PowerTransformer
# =============================================================================
class TestPowerTransformer:

    def test_effective_capacity_uses_onaf2(self):
        t = PowerTransformer(
            name="T", rated_mva=10, rated_mva_onaf=12.5, rated_mva_onaf2=15,
        )
        assert t.effective_capacity_mva == 15

    def test_falls_back_to_onaf(self):
        t = PowerTransformer(name="T", rated_mva=10, rated_mva_onaf=12.5)
        assert t.effective_capacity_mva == 12.5

    def test_falls_back_to_rated(self):
        t = PowerTransformer(name="T", rated_mva=10)
        assert t.effective_capacity_mva == 10


# =============================================================================
# Substation — capacidad y carga
# =============================================================================
class TestCapacityAndLoad:

    def test_total_capacity_sums_transformers(self, trafo_10mva, trafo_15mva):
        s = Substation(name="SE Pastaza")
        s.transformers = [trafo_10mva, trafo_15mva]
        # ONAF: 12.5 + 18 = 30.5
        assert s.total_capacity_mva() == 30.5

    def test_total_demand_uses_rms(self, feeder_4mw, feeder_5mw):
        s = Substation(name="SE")
        s.feeders = [feeder_4mw, feeder_5mw]
        # P = 9 MW, Q = 3.5 MVAr → S ≈ 9.66 MVA
        assert s.total_demand_mva() == pytest.approx(
            math.hypot(9, 3.5), rel=0.01,
        )

    def test_loading_pct(self, trafo_10mva, feeder_4mw):
        s = Substation(name="SE")
        s.transformers = [trafo_10mva]   # 12.5 MVA
        s.feeders = [feeder_4mw]         # ~4.27 MVA
        # 4.27 / 12.5 ≈ 34%
        assert 30.0 < s.loading_pct() < 40.0

    def test_n_minus_1_capacity(self, trafo_10mva, trafo_15mva):
        s = Substation(name="SE")
        s.transformers = [trafo_10mva, trafo_15mva]
        # Sin el más grande (T2=18 ONAF): queda T1=12.5
        assert s.n_minus_1_capacity_mva() == 12.5

    def test_n_minus_1_zero_with_single_unit(self, trafo_10mva):
        s = Substation(name="SE", transformers=[trafo_10mva])
        assert s.n_minus_1_capacity_mva() == 0.0
        # Por tanto loading N-1 es infinito (sin redundancia)
        assert s.n_minus_1_loading_pct() == float("inf")

    def test_reserve_positive_when_undermanded(self, trafo_15mva, feeder_4mw):
        s = Substation(name="SE")
        s.transformers = [trafo_15mva]      # 18 MVA
        s.feeders = [feeder_4mw]            # ~4.27 MVA
        assert s.reserve_mva() > 13.0


# =============================================================================
# Cortocircuito en barra MT
# =============================================================================
class TestShortCircuit:

    def test_zero_when_no_transformers(self):
        s = Substation(name="empty")
        assert s.short_circuit_mt_bus_ka() == 0.0

    def test_short_circuit_reasonable_value(self, trafo_10mva):
        # Trafo 10 MVA, Z=8% → SCC nominal aprox 10/0.08 = 125 MVA
        # En 22.8 kV → ~3.16 kA. Con AT fuerte (1500 MVA) la limitación
        # mayor es el trafo, no la fuente.
        s = Substation(
            name="SE", short_circuit_at_at_bus_mva=1500.0,
            voltage_mt_kv=22.8,
        )
        s.transformers = [trafo_10mva]
        ka = s.short_circuit_mt_bus_ka()
        # Esperado entre 2 y 4 kA (rango realista)
        assert 2.0 < ka < 4.5

    def test_two_transformers_increase_short_circuit(self,
                                                       trafo_10mva,
                                                       trafo_15mva):
        s_one = Substation(name="SE")
        s_one.transformers = [trafo_10mva]

        s_two = Substation(name="SE")
        s_two.transformers = [trafo_10mva, trafo_15mva]

        # Más trafos en paralelo → menor Z equivalente → mayor I_cc
        assert s_two.short_circuit_mt_bus_ka() > s_one.short_circuit_mt_bus_ka()


# =============================================================================
# Estado de operación
# =============================================================================
class TestStatus:

    def test_overload_status(self, trafo_10mva):
        # Trafo de 12.5 MVA con demanda de 15 MVA → sobrecarga
        s = Substation(
            name="SE", transformers=[trafo_10mva],
            feeders=[FeederBay(name="F", expected_load_mw=14, expected_load_mvar=5)],
        )
        assert s.status() == SubstationStatus.OVERLOAD

    def test_warning_status(self, trafo_10mva):
        # Carga ~85% → warning
        s = Substation(
            name="SE", transformers=[trafo_10mva],   # 12.5 MVA ONAF
            feeders=[FeederBay(name="F", expected_load_mw=10.5, expected_load_mvar=2)],
        )
        assert s.status() == SubstationStatus.WARNING

    def test_n_minus_1_fail_status(self, trafo_10mva, trafo_15mva):
        # Carga 14 MVA, capacidad 30.5 (ok) pero N-1 (12.5) la deja sobrecargada
        s = Substation(
            name="SE", transformers=[trafo_10mva, trafo_15mva],
            feeders=[FeederBay(name="F", expected_load_mw=13, expected_load_mvar=3)],
        )
        assert s.status() == SubstationStatus.N_MINUS_1_FAIL

    def test_ok_status_with_low_load(self, trafo_10mva):
        s = Substation(
            name="SE", transformers=[trafo_10mva],
            feeders=[FeederBay(name="F", expected_load_mw=4, expected_load_mvar=1)],
        )
        assert s.status() == SubstationStatus.OK

    def test_unknown_when_empty(self):
        s = Substation(name="empty")
        assert s.status() == SubstationStatus.UNKNOWN


# =============================================================================
# Selector de capacidad nominal
# =============================================================================
class TestSelectTransformer:

    def test_simple_selection(self):
        # Demanda 8 MVA, 1 unidad, sin N-1 → 10 MVA con margen 20%
        rating = select_transformer_for_load(
            demand_mva=8.0, n_units=1,
            redundancy_n1=False, margin_pct=20.0,
        )
        # 8 × 1.20 = 9.6 → próxima: 10
        assert rating == 10.0

    def test_n_minus_1_doubles_size_required(self):
        # Demanda 10 MVA, 2 unidades con N-1 → cada una debe cubrir 12 MVA
        rating = select_transformer_for_load(
            demand_mva=10.0, n_units=2,
            redundancy_n1=True, margin_pct=20.0,
        )
        # 10 × 1.20 / 1 = 12 → próxima: 12.5
        assert rating == 12.5

    def test_demanding_load_picks_max(self):
        rating = select_transformer_for_load(
            demand_mva=200.0, n_units=1, redundancy_n1=False,
        )
        # Excede catálogo → devuelve el mayor
        assert rating == 33.33

    def test_zero_load_returns_none(self):
        assert select_transformer_for_load(0.0) is None


# =============================================================================
# Detección desde Network
# =============================================================================
class TestDetectFromNetwork:

    def test_detect_substations_returns_barra_se_buses(self):
        from redes_engine.core.graph import Bus, BusType, VoltageLevel
        from redes_engine.core.network import Network

        net = Network(name="N")
        net.add_bus(Bus(
            id="SE1", geometry=(0, 0), voltage_kv=22.8,
            level=VoltageLevel.MT_22_8KV, bus_type=BusType.BARRA_SE,
        ))
        net.add_bus(Bus(
            id="P1", geometry=(1, 0), voltage_kv=22.8,
            level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT,
        ))
        ses = detect_substations(net)
        assert ses == ["SE1"]


# =============================================================================
# Summary
# =============================================================================
class TestSummary:

    def test_summary_has_all_keys(self, trafo_10mva, feeder_4mw):
        s = Substation(name="SE Test")
        s.transformers = [trafo_10mva]
        s.feeders = [feeder_4mw]
        d = s.summary()
        for k in ("name", "topology", "n_transformers", "total_capacity_mva",
                  "total_demand_mva", "loading_pct", "status"):
            assert k in d
