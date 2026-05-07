# -*- coding: utf-8 -*-
"""
Tests del contenedor multifile `.rsproj` v2.0.

Verifican:
    - Round-trip Network → ZIP → Network preserva estructura
    - Resultados (calculos.json) se preservan
    - Historial y catálogo opcionales
    - Compatibilidad: cargar archivo legacy v1.0 produce un container v2.0
    - Auto-detección por contenido (PK… vs JSON plano)
"""

import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.persistence import (
    RSProject,
    RSProjectContainer,
    RSProjectError,
    load_container,
    load_container_from_bytes,
    save_container,
    save_project,
)


@pytest.fixture
def network():
    from redes_engine.examples.urbanizacion_mixta import (
        build_urbanizacion_pastaza,
    )
    return build_urbanizacion_pastaza()


# =============================================================================
# Round-trip básico
# =============================================================================
class TestContainerRoundTrip:

    def test_save_load_preserves_network_topology(self, tmp_path, network):
        path = tmp_path / "demo.rsproj"
        c = RSProjectContainer.from_network(
            network, author="Iván", company="Ecuacier",
            description="Demo Pastaza", crs="EPSG:32717",
        )
        save_container(c, str(path))

        assert path.exists()
        # Es un ZIP real (firma "PK")
        with open(path, "rb") as f:
            assert f.read(2) == b"PK"

        loaded = load_container(str(path))
        assert len(loaded.network.buses) == len(network.buses)
        assert len(loaded.network.branches) == len(network.branches)
        assert len(loaded.network.assets) == len(network.assets)
        assert loaded.metadata.author == "Iván"
        assert loaded.metadata.company == "Ecuacier"
        assert loaded.metadata.crs == "EPSG:32717"

    def test_calculos_field_persisted(self, tmp_path, network):
        path = tmp_path / "with_calc.rsproj"
        calc = {
            "power_flow": {"converged": True, "losses_pct": 2.5},
            "compliance": {"overall_status": "ok", "n_violations": 0},
        }
        c = RSProjectContainer.from_network(network, calculos=calc)
        save_container(c, str(path))

        loaded = load_container(str(path))
        assert loaded.calculos["power_flow"]["converged"] is True
        assert loaded.calculos["power_flow"]["losses_pct"] == 2.5
        assert loaded.calculos["compliance"]["n_violations"] == 0

    def test_historial_preserved(self, tmp_path, network):
        path = tmp_path / "with_log.rsproj"
        log = "2026-05-04 10:00 - proyecto creado\n2026-05-04 11:00 - flujo PF ok\n"
        c = RSProjectContainer.from_network(network, historial=log)
        save_container(c, str(path))

        loaded = load_container(str(path))
        assert loaded.historial == log

    def test_catalogo_optional_omitted(self, tmp_path, network):
        path = tmp_path / "no_catalog.rsproj"
        c = RSProjectContainer.from_network(network)
        save_container(c, str(path))
        # Sin catálogo, la entrada no debe estar
        with zipfile.ZipFile(str(path), "r") as zf:
            assert "catalogo.json" not in zf.namelist()

    def test_catalogo_persisted_when_present(self, tmp_path, network):
        path = tmp_path / "with_catalog.rsproj"
        cat = {"PSC-12500": {"materials": [{"item": "X1", "cantidad": 1}]}}
        c = RSProjectContainer.from_network(network, catalogo=cat)
        save_container(c, str(path))

        loaded = load_container(str(path))
        assert loaded.catalogo == cat


# =============================================================================
# Manifiesto y estructura del ZIP
# =============================================================================
class TestContainerStructure:

    def test_zip_contains_required_entries(self, tmp_path, network):
        path = tmp_path / "demo.rsproj"
        c = RSProjectContainer.from_network(network)
        save_container(c, str(path))

        with zipfile.ZipFile(str(path), "r") as zf:
            names = set(zf.namelist())
        assert "manifest.json" in names
        assert "metadata.json" in names
        assert "network.json" in names
        assert "calculos.json" in names
        assert "historial.log" in names

    def test_manifest_has_format_version(self, tmp_path, network):
        path = tmp_path / "demo.rsproj"
        c = RSProjectContainer.from_network(network)
        save_container(c, str(path))

        with zipfile.ZipFile(str(path), "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["format_version"] == "2.0"
        assert "engine_version" in manifest


# =============================================================================
# Compatibilidad legacy v1 (JSON plano)
# =============================================================================
class TestLegacyCompatibility:

    def test_load_legacy_json_produces_container(self, tmp_path, network):
        # Guardar en formato legacy v1 (JSON plano)
        legacy_path = tmp_path / "legacy.rsproj"
        legacy = RSProject.from_network(network, author="Legacy User")
        save_project(legacy, str(legacy_path))

        # Cargar con la API nueva → debe devolver un RSProjectContainer
        loaded = load_container(str(legacy_path))
        assert isinstance(loaded, RSProjectContainer)
        assert loaded.metadata.author == "Legacy User"
        assert len(loaded.network.buses) == len(network.buses)
        # Sin calculos (v1 no los guardaba)
        assert loaded.calculos == {}

    def test_load_from_bytes_detects_zip_vs_json(self, tmp_path, network):
        # ZIP
        c = RSProjectContainer.from_network(network)
        zip_bytes = c.write_zip_bytes()
        loaded_zip = load_container_from_bytes(zip_bytes)
        assert isinstance(loaded_zip, RSProjectContainer)
        assert len(loaded_zip.network.buses) == len(network.buses)

        # JSON plano
        legacy = RSProject.from_network(network)
        json_bytes = json.dumps(legacy.to_dict(), ensure_ascii=False).encode("utf-8")
        loaded_json = load_container_from_bytes(json_bytes)
        assert isinstance(loaded_json, RSProjectContainer)
        assert len(loaded_json.network.buses) == len(network.buses)


# =============================================================================
# Errores
# =============================================================================
class TestContainerErrors:

    def test_corrupt_zip_raises(self, tmp_path):
        path = tmp_path / "bad.rsproj"
        path.write_bytes(b"PK\x03\x04corrupt-not-actually-a-zip")
        with pytest.raises(RSProjectError):
            load_container(str(path))

    def test_zip_without_network_raises(self, tmp_path):
        path = tmp_path / "empty.rsproj"
        with zipfile.ZipFile(str(path), "w") as zf:
            zf.writestr("manifest.json", "{}")
        with pytest.raises(RSProjectError, match="network"):
            load_container(str(path))

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RSProjectError, match="no encontrado"):
            load_container(str(tmp_path / "nonexistent.rsproj"))
