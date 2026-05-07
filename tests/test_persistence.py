# -*- coding: utf-8 -*-
"""Tests del módulo persistence (G5) — formato .rsproj."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.persistence import (
    RSProject, RSProjectError, dict_to_network,
    load_project, network_to_dict, save_project,
)


@pytest.fixture
def network():
    from redes_engine.examples.urbanizacion_mixta import (
        build_urbanizacion_pastaza,
    )
    return build_urbanizacion_pastaza()


# =============================================================================
# Serialización Network
# =============================================================================
class TestSerialization:

    def test_round_trip_preserves_buses(self, network):
        d = network_to_dict(network)
        net2 = dict_to_network(d)
        assert set(net2.buses.keys()) == set(network.buses.keys())

    def test_round_trip_preserves_branches(self, network):
        d = network_to_dict(network)
        net2 = dict_to_network(d)
        assert set(net2.branches.keys()) == set(network.branches.keys())
        # Tipos preservados
        for bid, br in network.branches.items():
            assert net2.branches[bid].branch_type == br.branch_type

    def test_round_trip_preserves_assets(self, network):
        d = network_to_dict(network)
        net2 = dict_to_network(d)
        assert set(net2.assets.keys()) == set(network.assets.keys())
        # Capacity preservado para BESS
        for aid, a in network.assets.items():
            assert net2.assets[aid].rated_kw == a.rated_kw
            if a.capacity_kwh is not None:
                assert net2.assets[aid].capacity_kwh == a.capacity_kwh


# =============================================================================
# RSProject
# =============================================================================
class TestRSProject:

    def test_from_network(self, network):
        proj = RSProject.from_network(
            network, author="Ing. Test",
            company="Ejemplo S.A.",
        )
        assert proj.network is network
        assert proj.metadata.author == "Ing. Test"
        assert proj.metadata.created_at != ""

    def test_round_trip_dict(self, network):
        proj = RSProject.from_network(network, author="X")
        d = proj.to_dict()
        proj2 = RSProject.from_dict(d)
        assert proj2.metadata.author == "X"
        assert len(proj2.network.buses) == len(network.buses)

    def test_unsupported_format_raises(self, network):
        proj = RSProject.from_network(network)
        d = proj.to_dict()
        d["format_version"] = "99.0"
        with pytest.raises(RSProjectError, match="no soportado"):
            RSProject.from_dict(d)


# =============================================================================
# I/O en disco
# =============================================================================
class TestProjectIO:

    def test_save_and_load(self, network, tmp_path):
        proj = RSProject.from_network(network, author="Test")
        path = tmp_path / "test.rsproj"
        save_project(proj, str(path))
        assert os.path.exists(path)
        # Cargar
        proj2 = load_project(str(path))
        assert proj2.metadata.author == "Test"
        assert len(proj2.network.buses) == len(network.buses)

    def test_load_nonexistent_raises(self):
        with pytest.raises(RSProjectError, match="no encontrado"):
            load_project("/no/such/file.rsproj")

    def test_load_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "bad.rsproj"
        bad.write_text("{ invalid json", encoding="utf-8")
        with pytest.raises(RSProjectError):
            load_project(str(bad))


# =============================================================================
# API endpoints
# =============================================================================
fastapi = pytest.importorskip("fastapi", reason="fastapi no instalado")


class TestProjectAPIEndpoints:

    @pytest.fixture(autouse=True)
    def clean_store(self):
        from redes_engine.api.storage import get_store
        get_store().clear()
        yield
        get_store().clear()

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from redes_engine.api.main import app
        return TestClient(app)

    def test_save_and_reload_via_api(self, client):
        # Cargar demo
        nid = client.post("/api/v1/demo/load").json()["id"]
        # Guardar como .rsproj (formato v2.0 = contenedor ZIP)
        res = client.post(
            f"/api/v1/projects/save/{nid}",
            json={"author": "API Test"},
        )
        assert res.status_code == 200
        rsproj_bytes = res.content
        # Es un ZIP (firma "PK")
        assert rsproj_bytes[:2] == b"PK"

        # Verificar contenido del ZIP
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(rsproj_bytes), "r") as zf:
            names = set(zf.namelist())
            assert "manifest.json" in names
            assert "network.json" in names
            assert "metadata.json" in names
            meta = json.loads(zf.read("metadata.json").decode("utf-8"))
            assert meta["author"] == "API Test"

        # Subirlo de vuelta
        files = {"file": ("test.rsproj", rsproj_bytes, "application/zip")}
        res2 = client.post("/api/v1/projects/load", files=files)
        assert res2.status_code == 201
        assert res2.json()["n_buses"] == 8
