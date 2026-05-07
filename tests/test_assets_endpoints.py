# -*- coding: utf-8 -*-
"""Tests de endpoints de asset editing (G6)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi no instalado")


@pytest.fixture(autouse=True)
def clean_store():
    from redes_engine.api.storage import get_store
    get_store().clear()
    yield
    get_store().clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from redes_engine.api.main import app
    return TestClient(app)


@pytest.fixture
def loaded_network(client):
    return client.post("/api/v1/demo/load").json()["id"]


# =============================================================================
# POST /networks/{id}/assets
# =============================================================================
class TestAddAsset:

    def test_add_residential_load(self, client, loaded_network):
        res = client.post(
            f"/api/v1/networks/{loaded_network}/assets",
            json={
                "bus_id": "Bus_010",
                "asset_type": "load_residencial",
                "rated_kw": 5.5,
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["bus_id"] == "Bus_010"
        assert data["rated_kw"] == 5.5

    def test_add_bess_with_default_capacity(self, client, loaded_network):
        res = client.post(
            f"/api/v1/networks/{loaded_network}/assets",
            json={
                "bus_id": "Bus_010",
                "asset_type": "bess_btm",
                "rated_kw": 5.0,
            },
        )
        assert res.status_code == 201
        # Default: capacity = 2 × rated_kw = 10 kWh
        assert res.json()["capacity_kwh"] == 10.0

    def test_add_with_catalog_model_tesla(self, client, loaded_network):
        res = client.post(
            f"/api/v1/networks/{loaded_network}/assets",
            json={
                "bus_id": "Bus_010",
                "asset_type": "bess_btm",
                "rated_kw": 99,   # se sobrescribe por el catálogo
                "catalog_model": "tesla_powerwall_3",
            },
        )
        assert res.status_code == 201
        data = res.json()
        # Powerwall 3: 11.5 kW, 13.5 kWh
        assert abs(data["rated_kw"] - 11.5) < 0.1
        assert abs(data["capacity_kwh"] - 13.5) < 0.1

    def test_add_invalid_bus_400(self, client, loaded_network):
        res = client.post(
            f"/api/v1/networks/{loaded_network}/assets",
            json={
                "bus_id": "INEXISTENTE",
                "asset_type": "load_residencial",
                "rated_kw": 5,
            },
        )
        assert res.status_code == 400

    def test_add_invalid_type_400(self, client, loaded_network):
        res = client.post(
            f"/api/v1/networks/{loaded_network}/assets",
            json={
                "bus_id": "Bus_010",
                "asset_type": "magic_unicorn",
                "rated_kw": 5,
            },
        )
        assert res.status_code == 400

    def test_add_invalid_catalog_404(self, client, loaded_network):
        res = client.post(
            f"/api/v1/networks/{loaded_network}/assets",
            json={
                "bus_id": "Bus_010",
                "asset_type": "bess_btm",
                "rated_kw": 5,
                "catalog_model": "nonexistent_model",
            },
        )
        assert res.status_code == 404


# =============================================================================
# DELETE /networks/{id}/assets/{asset_id}
# =============================================================================
class TestDeleteAsset:

    def test_delete_existing(self, client, loaded_network):
        # Asset ya existente en demo: LD_010
        res = client.delete(
            f"/api/v1/networks/{loaded_network}/assets/LD_010"
        )
        assert res.status_code == 204

    def test_delete_nonexistent_404(self, client, loaded_network):
        res = client.delete(
            f"/api/v1/networks/{loaded_network}/assets/NOPE"
        )
        assert res.status_code == 404


# =============================================================================
# GET /networks/{id}/assets
# =============================================================================
class TestListAssets:

    def test_list_all(self, client, loaded_network):
        res = client.get(f"/api/v1/networks/{loaded_network}/assets")
        assert res.status_code == 200
        assert len(res.json()) == 9   # demo Pastaza tiene 9 assets

    def test_list_by_bus(self, client, loaded_network):
        res = client.get(
            f"/api/v1/networks/{loaded_network}/assets?bus_id=Bus_010"
        )
        assert res.status_code == 200
        assets = res.json()
        # Bus_010 tiene 4 assets en la demo (LD, PV, BESS, EV)
        assert len(assets) == 4
        for a in assets:
            assert a["bus_id"] == "Bus_010"


# =============================================================================
# Catálogos
# =============================================================================
class TestCatalogEndpoints:

    def test_list_ev_chargers(self, client):
        res = client.get("/api/v1/catalogs/ev_chargers")
        assert res.status_code == 200
        data = res.json()
        assert len(data) > 5
        for p in data:
            assert "model" in p
            assert "manufacturer" in p
            assert "rated_kw" in p

    def test_list_bess(self, client):
        res = client.get("/api/v1/catalogs/bess")
        assert res.status_code == 200
        data = res.json()
        assert len(data) > 5
        for p in data:
            assert "capacity_kwh" in p
            assert "duration_hours" in p
