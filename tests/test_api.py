# -*- coding: utf-8 -*-
"""
Tests del API REST con FastAPI TestClient.

Cubre:
    - Health endpoint
    - CRUD de networks (incluyendo /demo/load)
    - Solve, hosting, timeseries
    - Endpoints GeoJSON para el frontend
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

# Skip si FastAPI no está
fastapi = pytest.importorskip("fastapi", reason="fastapi no instalado")

from fastapi.testclient import TestClient

from redes_engine.api.main import app
from redes_engine.api.storage import get_store


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture(autouse=True)
def clean_store():
    """Limpiar store antes de cada test."""
    get_store().clear()
    yield
    get_store().clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def loaded_network(client):
    """Carga la red demo y devuelve el id."""
    res = client.post("/api/v1/demo/load")
    assert res.status_code == 201 or res.status_code == 200
    return res.json()["id"]


# =============================================================================
# Health
# =============================================================================
class TestHealth:

    def test_health_endpoint(self, client):
        res = client.get("/api/v1/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "opendss_available" in data
        assert data["networks_count"] == 0


# =============================================================================
# Networks CRUD
# =============================================================================
class TestNetworksCRUD:

    def test_demo_load(self, client):
        res = client.post("/api/v1/demo/load")
        assert res.status_code in (200, 201)
        data = res.json()
        assert "id" in data
        assert data["name"] == "ElPastaza"
        assert data["n_buses"] == 8

    def test_list_after_demo(self, client):
        client.post("/api/v1/demo/load")
        res = client.get("/api/v1/networks")
        assert res.status_code == 200
        networks = res.json()
        assert len(networks) == 1

    def test_get_detail(self, client, loaded_network):
        res = client.get(f"/api/v1/networks/{loaded_network}")
        assert res.status_code == 200
        detail = res.json()
        assert detail["n_buses"] == 8
        assert len(detail["buses"]) == 8
        assert len(detail["branches"]) == 7
        assert len(detail["assets"]) == 9

    def test_get_unknown_network_404(self, client):
        res = client.get("/api/v1/networks/INEXISTENTE")
        assert res.status_code == 404

    def test_delete_network(self, client, loaded_network):
        res = client.delete(f"/api/v1/networks/{loaded_network}")
        assert res.status_code == 204
        # Confirmar que ya no existe
        res2 = client.get(f"/api/v1/networks/{loaded_network}")
        assert res2.status_code == 404

    def test_create_network_from_geojson(self, client):
        layers = {
            "postes_mt": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature",
                     "properties": {"NUM_SEQ": "P1", "VOLTAJE": 22.8},
                     "geometry": {"type": "Point", "coordinates": [0, 0]}},
                    {"type": "Feature",
                     "properties": {"NUM_SEQ": "P2", "VOLTAJE": 22.8},
                     "geometry": {"type": "Point", "coordinates": [100, 0]}},
                ]
            },
            "tramos_mt": {
                "type": "FeatureCollection",
                "features": [
                    {"type": "Feature",
                     "properties": {
                         "NUM_SEQ": "L1",
                         "NODO_I": "P1", "NODO_J": "P2",
                         "AMPACIDAD": 200, "LONGITUD": 100,
                     },
                     "geometry": {
                         "type": "LineString",
                         "coordinates": [[0, 0], [100, 0]],
                     }},
                ]
            }
        }
        res = client.post("/api/v1/networks", json={
            "name": "API_Test",
            "layers": layers,
        })
        assert res.status_code == 201
        data = res.json()
        assert data["n_buses"] == 2
        assert data["n_branches"] == 1


# =============================================================================
# Análisis (requieren OpenDSS)
# =============================================================================
opendss = pytest.importorskip(
    "opendssdirect", reason="opendssdirect no instalado",
)


class TestAnalysis:

    def test_solve(self, client, loaded_network):
        res = client.post(f"/api/v1/networks/{loaded_network}/solve")
        assert res.status_code == 200
        data = res.json()
        assert data["converged"] is True
        assert data["iterations"] >= 1
        assert len(data["bus_voltages"]) >= 5
        assert len(data["branch_flows"]) >= 5
        # Compliance debe estar reportado
        assert data["n_violations"] >= 0
        assert data["n_warnings"] >= 0

    def test_hosting(self, client, loaded_network):
        res = client.post(
            f"/api/v1/networks/{loaded_network}/hosting",
            json={"n_critical_hours": 5, "max_kw": 100, "tolerance_kw": 10},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["n_buses_analyzed"] == 8
        assert len(data["bus_results"]) == 8
        assert data["total_pv_capacity_kw"] >= 0

    def test_timeseries_short(self, client, loaded_network):
        res = client.post(
            f"/api/v1/networks/{loaded_network}/timeseries",
            json={"hours": 12, "scenario_name": "Test"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["n_hours_simulated"] == 12
        assert data["scenario_name"] == "Test"


# =============================================================================
# GeoJSON endpoints
# =============================================================================
class TestGeoJSON:

    def test_topology_geojson(self, client, loaded_network):
        res = client.get(f"/api/v1/networks/{loaded_network}/geojson")
        assert res.status_code == 200
        data = res.json()
        assert "buses" in data
        assert "lines" in data
        assert "transformers" in data
        assert data["buses"]["type"] == "FeatureCollection"
        assert len(data["buses"]["features"]) == 8
        assert len(data["lines"]["features"]) == 6
        assert len(data["transformers"]["features"]) == 1

    def test_results_geojson_without_solve(self, client, loaded_network):
        """Sin solve, los resultados aparecen como compliance=unknown."""
        res = client.get(f"/api/v1/networks/{loaded_network}/results/geojson")
        assert res.status_code == 200
        data = res.json()
        for feat in data["buses"]["features"]:
            assert feat["properties"]["compliance"] == "unknown"


class TestResultsAfterSolve:
    """Tests que requieren ejecutar solve antes."""

    def test_results_after_solve(self, client, loaded_network):
        # Ejecutar solve
        client.post(f"/api/v1/networks/{loaded_network}/solve")
        # Ahora los resultados deben tener valores
        res = client.get(f"/api/v1/networks/{loaded_network}/results/geojson")
        data = res.json()
        # Al menos algunos buses deben tener compliance != unknown
        compliances = [
            feat["properties"]["compliance"]
            for feat in data["buses"]["features"]
        ]
        non_unknown = [c for c in compliances if c != "unknown"]
        assert len(non_unknown) > 0


# =============================================================================
# Frontend
# =============================================================================
class TestFrontend:

    def test_index_returns_html(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert "html" in res.headers.get("content-type", "").lower()

    def test_static_assets(self, client):
        res = client.get("/static/app.js")
        assert res.status_code == 200
        assert "javascript" in res.headers.get("content-type", "").lower() or \
               "text" in res.headers.get("content-type", "").lower()


# =============================================================================
# OpenAPI schema disponible
# =============================================================================
class TestOpenAPI:

    def test_docs_available(self, client):
        res = client.get("/docs")
        assert res.status_code == 200

    def test_openapi_json(self, client):
        res = client.get("/openapi.json")
        assert res.status_code == 200
        data = res.json()
        # Verificar que los endpoints clave están listados
        paths = data["paths"]
        assert "/api/v1/networks" in paths
        assert "/api/v1/health" in paths
        assert any("/solve" in p for p in paths)
        assert any("/hosting" in p for p in paths)
