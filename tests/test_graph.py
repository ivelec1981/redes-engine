# -*- coding: utf-8 -*-
"""
Tests del modelo de grafo unificado.

Ejecutar:
    pytest tests/ -v
"""

import os
import sys

# Permitir ejecutar tests sin instalar el paquete
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.core.graph import (
    Asset, AssetType,
    Branch, BranchType,
    Bus, BusType,
    VoltageLevel,
)
from redes_engine.core.network import Network


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def empty_net():
    return Network("Test")


@pytest.fixture
def small_net():
    """Red simple A—B con un transformador 22.8/0.220."""
    net = Network("Small")
    net.add_bus(Bus(
        id="A", geometry=(0, 0), voltage_kv=22.8,
        level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT,
    ))
    net.add_bus(Bus(
        id="B", geometry=(0, 1), voltage_kv=0.220,
        level=VoltageLevel.BT_220_127, bus_type=BusType.POZO_BT,
    ))
    net.add_branch(Branch(
        id="T", bus_from="A", bus_to="B",
        branch_type=BranchType.TRANSFORMER,
        geometry=[(0, 0), (0, 1)],
        length_m=1.0, kva=50.0,
        kv_primary=22.8, kv_secondary=0.220,
        impedance_pu=0.04,
    ))
    return net


# =============================================================================
# BUS
# =============================================================================

class TestBus:
    def test_creation(self):
        b = Bus(
            id="B1", geometry=(100, 200), voltage_kv=22.8,
            level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT,
        )
        assert b.id == "B1"
        assert b.voltage_kv == 22.8

    def test_is_mt_vs_bt(self):
        mt = Bus(
            id="MT", geometry=(0, 0), voltage_kv=22.8,
            level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT,
        )
        bt = Bus(
            id="BT", geometry=(0, 0), voltage_kv=0.220,
            level=VoltageLevel.BT_220_127, bus_type=BusType.POZO_BT,
        )
        assert mt.is_mt() and not mt.is_bt()
        assert bt.is_bt() and not bt.is_mt()

    def test_hash_equality(self):
        b1 = Bus(id="X", geometry=(0, 0), voltage_kv=22.8,
                 level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT)
        b2 = Bus(id="X", geometry=(99, 99), voltage_kv=11.0,
                 level=VoltageLevel.MT_13_8KV, bus_type=BusType.POSTE_BT)
        # Mismo ID → iguales
        assert b1 == b2
        assert hash(b1) == hash(b2)


# =============================================================================
# NETWORK — Agregación
# =============================================================================

class TestNetworkAdd:
    def test_add_bus(self, empty_net):
        b = Bus(id="B1", geometry=(0, 0), voltage_kv=22.8,
                level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT)
        empty_net.add_bus(b)
        assert "B1" in empty_net.buses

    def test_add_duplicate_bus_raises(self, empty_net):
        b = Bus(id="B1", geometry=(0, 0), voltage_kv=22.8,
                level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT)
        empty_net.add_bus(b)
        with pytest.raises(ValueError):
            empty_net.add_bus(b)

    def test_branch_requires_existing_buses(self, empty_net):
        with pytest.raises(ValueError):
            empty_net.add_branch(Branch(
                id="L1", bus_from="X", bus_to="Y",
                branch_type=BranchType.LINE_AEREA_MT,
                geometry=[], length_m=10,
            ))

    def test_transformer_must_change_voltage(self, empty_net):
        for bid in ("A", "B"):
            empty_net.add_bus(Bus(
                id=bid, geometry=(0, 0), voltage_kv=22.8,
                level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT,
            ))
        with pytest.raises(ValueError, match="voltajes iguales"):
            empty_net.add_branch(Branch(
                id="T", bus_from="A", bus_to="B",
                branch_type=BranchType.TRANSFORMER,
                geometry=[(0, 0), (1, 1)], length_m=1,
                kva=50.0, kv_primary=22.8, kv_secondary=22.8,
            ))

    def test_storage_requires_capacity(self, empty_net):
        empty_net.add_bus(Bus(
            id="B1", geometry=(0, 0), voltage_kv=0.220,
            level=VoltageLevel.BT_220_127, bus_type=BusType.MEDIDOR,
        ))
        with pytest.raises(ValueError, match="capacity_kwh"):
            empty_net.add_asset(Asset(
                id="BESS", bus_id="B1",
                asset_type=AssetType.BESS_BTM,
                rated_kw=5.0,
                # ¡Falta capacity_kwh!
            ))


# =============================================================================
# NETWORK — Topología
# =============================================================================

class TestTopology:
    def test_neighbors(self, small_net):
        assert "B" in small_net.neighbors("A")
        assert "A" in small_net.neighbors("B")

    def test_path_finding(self):
        net = Network("PathTest")
        for bid in ("A", "B", "C", "D"):
            net.add_bus(Bus(
                id=bid, geometry=(0, 0), voltage_kv=22.8,
                level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT,
            ))
        net.add_branch(Branch(
            id="AB", bus_from="A", bus_to="B",
            branch_type=BranchType.LINE_AEREA_MT,
            geometry=[], length_m=10,
        ))
        net.add_branch(Branch(
            id="BC", bus_from="B", bus_to="C",
            branch_type=BranchType.LINE_AEREA_MT,
            geometry=[], length_m=10,
        ))
        net.add_branch(Branch(
            id="CD", bus_from="C", bus_to="D",
            branch_type=BranchType.LINE_AEREA_MT,
            geometry=[], length_m=10,
        ))
        path = net.path("A", "D")
        assert path == ["A", "B", "C", "D"]

    def test_disconnected_components(self):
        net = Network("Disc")
        # Componente 1: A—B
        net.add_bus(Bus(id="A", geometry=(0, 0), voltage_kv=22.8,
                        level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT))
        net.add_bus(Bus(id="B", geometry=(0, 0), voltage_kv=22.8,
                        level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT))
        net.add_branch(Branch(id="AB", bus_from="A", bus_to="B",
                              branch_type=BranchType.LINE_AEREA_MT,
                              geometry=[], length_m=10))
        # Componente 2: C aislado
        net.add_bus(Bus(id="C", geometry=(0, 0), voltage_kv=22.8,
                        level=VoltageLevel.MT_22_8KV, bus_type=BusType.POSTE_MT))

        assert not net.is_connected()
        comps = net.connected_components()
        assert len(comps) == 2

    def test_root_bus_is_highest_voltage(self, small_net):
        root = small_net.find_root_bus()
        assert root.id == "A"  # 22.8 kV > 0.220 kV


# =============================================================================
# ASSETS
# =============================================================================

class TestAssets:
    def test_load_classification(self):
        a = Asset(id="LD", bus_id="X", asset_type=AssetType.LOAD_RESIDENCIAL,
                  rated_kw=4.0)
        assert a.is_load()
        assert not a.is_ev() and not a.is_pv() and not a.is_storage()

    def test_v2g_is_ev_and_storage(self):
        a = Asset(id="V2G", bus_id="X", asset_type=AssetType.V2G_BIDIRECTIONAL,
                  rated_kw=11.0, capacity_kwh=60.0)
        assert a.is_ev()
        assert a.is_storage()

    def test_pv_bess_hybrid_is_pv_and_storage(self):
        a = Asset(id="HYB", bus_id="X", asset_type=AssetType.PV_BESS_HYBRID,
                  rated_kw=10.0, capacity_kwh=20.0)
        assert a.is_pv()
        assert a.is_storage()

    def test_profile_indexing(self):
        profile = list(range(24))
        a = Asset(id="X", bus_id="B", asset_type=AssetType.LOAD_RESIDENCIAL,
                  rated_kw=4.0, profile_24h_kw=profile)
        assert a.power_at_hour(0) == 0
        assert a.power_at_hour(12) == 12
        assert a.power_at_hour(23) == 23

    def test_profile_fallback_to_rated(self):
        a = Asset(id="X", bus_id="B", asset_type=AssetType.LOAD_RESIDENCIAL,
                  rated_kw=5.5)
        assert a.power_at_hour(0) == 5.5  # sin perfil → usa rated_kw


# =============================================================================
# EJEMPLO INTEGRAL — Urbanización mixta
# =============================================================================

class TestUrbanizacionPastaza:

    @pytest.fixture
    def net(self):
        from redes_engine.examples.urbanizacion_mixta import build_urbanizacion_pastaza
        return build_urbanizacion_pastaza()

    def test_has_mt_and_bt_buses(self, net):
        mt = [b for b in net.buses.values() if b.is_mt()]
        bt = [b for b in net.buses.values() if b.is_bt()]
        assert len(mt) >= 3
        assert len(bt) >= 5

    def test_has_transformer(self, net):
        trafos = net.transformers()
        assert len(trafos) >= 1
        t = trafos[0]
        assert t.kv_primary == 22.8
        assert t.kv_secondary == 0.220

    def test_assets_diversity(self, net):
        """Verifica que la red tenga el mix completo de tipos."""
        types = {a.asset_type for a in net.assets.values()}
        assert AssetType.LOAD_RESIDENCIAL in types
        assert AssetType.SOLAR_PV_RESID in types
        assert AssetType.BESS_BTM in types
        assert AssetType.EV_CHARGER_AC_L2 in types
        assert AssetType.V2G_BIDIRECTIONAL in types
        assert AssetType.EV_CHARGER_DC_FAST in types
        assert AssetType.ALUMBRADO_PUBLICO in types

    def test_topology_connected(self, net):
        assert net.is_connected()

    def test_path_mt_to_meter(self, net):
        """Debe haber un camino desde el bus MT inicial hasta el medidor BT."""
        path = net.path("Bus_001", "Bus_010")
        assert path is not None
        assert path[0] == "Bus_001"
        assert path[-1] == "Bus_010"
        # Camino atraviesa un transformador
        # → debe contener 'Bus_003' (MT) y 'Bus_004' (BT) en secuencia
        assert "Bus_003" in path
        assert "Bus_004" in path

    def test_total_load_positive(self, net):
        assert net.total_load_kw() > 0

    def test_total_storage_capacity(self, net):
        # 10 (BTM Casa A) + 60 (V2G Casa B) + 50 (BESS comunal) = 120 kWh
        assert net.total_storage_kwh() == pytest.approx(120.0)


# =============================================================================
# EXPORTADOR OPENDSS
# =============================================================================

class TestOpenDSSExporter:

    def test_export_creates_file(self, tmp_path):
        from redes_engine.examples.urbanizacion_mixta import build_urbanizacion_pastaza
        from redes_engine.io.opendss_bridge import OpenDSSExporter

        net = build_urbanizacion_pastaza()
        out = tmp_path / "test_circuit.dss"
        OpenDSSExporter(net).export(str(out))
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        # Verifica que contenga las secciones críticas
        assert "New Circuit." in content
        assert "New Line." in content
        assert "New Transformer." in content
        assert "New Load." in content
        assert "New Generator." in content     # PV
        assert "New Storage." in content       # BESS
        assert "Solve" in content
