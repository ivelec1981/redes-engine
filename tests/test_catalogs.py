# -*- coding: utf-8 -*-
"""Tests del módulo catalogs (G3) — productos reales Tesla/ABB/BYD/CATL."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.catalogs import BESSCatalog, EVChargerCatalog
from redes_engine.core.graph import AssetType


# =============================================================================
# EVChargerCatalog
# =============================================================================
class TestEVChargerCatalog:

    @pytest.fixture
    def cat(self):
        return EVChargerCatalog.load_default()

    def test_loads_default(self, cat):
        assert len(cat) > 5
        # Debe haber al menos Tesla, ABB, Wallbox
        manuf = {p.manufacturer for p in cat}
        assert "Tesla" in manuf
        assert "ABB" in manuf

    def test_find_by_model(self, cat):
        p = cat.find_by_model("tesla_wall_connector_gen3")
        assert p is not None
        assert p.manufacturer == "Tesla"
        assert p.rated_kw > 0

    def test_filter_by_manufacturer(self, cat):
        teslas = cat.filter_by_manufacturer("Tesla")
        assert len(teslas) >= 2

    def test_filter_by_category(self, cat):
        ac_l2 = cat.filter_by_category("ev_ac_l2")
        assert len(ac_l2) >= 2
        for p in ac_l2:
            assert p.category == "ev_ac_l2"

    def test_v2g_products(self, cat):
        v2g = cat.v2g_products()
        assert len(v2g) >= 1
        for p in v2g:
            assert p.v2g_capable

    def test_to_asset(self, cat):
        p = cat.find_by_model("abb_terra_dc_50")
        asset = p.to_asset(asset_id="EV1", bus_id="Bus_010")
        assert asset.asset_type == AssetType.EV_CHARGER_DC_FAST
        assert asset.rated_kw == 50.0
        assert asset.bus_id == "Bus_010"

    def test_to_asset_v2g_has_capacity(self, cat):
        p = cat.find_by_model("wallbox_quasar_v2g")
        asset = p.to_asset(asset_id="V2G1", bus_id="Bus_010")
        assert asset.asset_type == AssetType.V2G_BIDIRECTIONAL
        assert asset.bidirectional is True
        assert asset.capacity_kwh is not None

    def test_cheapest_per_kw(self, cat):
        cheap = cat.cheapest_per_kw(category="ev_ac_l2")
        assert cheap is not None
        assert cheap.cost_per_kw_usd > 0


# =============================================================================
# BESSCatalog
# =============================================================================
class TestBESSCatalog:

    @pytest.fixture
    def cat(self):
        return BESSCatalog.load_default()

    def test_loads_default(self, cat):
        assert len(cat) > 5
        manuf = {p.manufacturer for p in cat}
        assert "Tesla" in manuf
        assert "BYD" in manuf
        assert "CATL" in manuf

    def test_powerwall_specs(self, cat):
        p = cat.find_by_model("tesla_powerwall_3")
        assert p is not None
        assert p.rated_kw > 0
        assert p.capacity_kwh > 10
        assert 0.85 <= p.round_trip_efficiency <= 1.0

    def test_megapack_is_grid_scale(self, cat):
        p = cat.find_by_model("tesla_megapack_3")
        assert p.category == "bess_grid_scale"
        assert p.capacity_kwh >= 1000

    def test_to_asset(self, cat):
        p = cat.find_by_model("tesla_powerwall_3")
        asset = p.to_asset(asset_id="BESS1", bus_id="Bus_010")
        assert asset.asset_type == AssetType.BESS_BTM
        assert asset.capacity_kwh == p.capacity_kwh
        assert asset.controllable is True
        assert asset.bidirectional is True

    def test_best_match(self, cat):
        # Pedimos al menos 50 kWh BTM
        p = cat.best_match(target_kwh=50.0, category="bess_btm")
        # Hay BTM con >=15 kWh; el más grande disponible
        assert p is not None
        # En BTM los más grandes andan en 15-16 kWh, igualmente devuelve algo
        assert p.capacity_kwh > 0

    def test_duration_property(self, cat):
        p = cat.find_by_model("tesla_megapack_3")
        # Megapack 3: ~2 horas de duración
        assert 1.5 <= p.duration_hours <= 5.0
