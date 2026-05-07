# -*- coding: utf-8 -*-
"""
Tests del writer QGIS — verifica que GeoJSON y QML generados sean
válidos y contengan los atributos esperados.
"""

import json
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.core.compliance import ARCERNNR_EC, ComplianceAnalyzer
from redes_engine.core.results import (
    BranchFlowResult, BusVoltageResult,
    ComplianceStatus, PowerFlowResult,
)
from redes_engine.io import qml_templates
from redes_engine.io.qgis_writer import QGISResultsWriter


# =============================================================================
# Fixtures: red mock + resultado mock
# =============================================================================
@pytest.fixture
def mock_network():
    from redes_engine.examples.urbanizacion_mixta import (
        build_urbanizacion_pastaza,
    )
    return build_urbanizacion_pastaza()


@pytest.fixture
def mock_result(mock_network):
    """Crea un PowerFlowResult sintético."""
    result = PowerFlowResult(
        converged=True, iterations=2,
        total_power_kw=63.89, total_power_kvar=4.96,
        total_losses_kw=1.976, losses_pct=3.09,
    )
    # Voltajes para cada bus
    for bus_id, bus in mock_network.buses.items():
        v_drop = -2.0 if bus.is_mt() else -0.3
        result.bus_voltages[bus_id] = BusVoltageResult(
            bus_id=bus_id,
            v_magnitude_kv=bus.voltage_kv * 1.02,
            v_pu=1.02,
            v_drop_pct=v_drop,
            angle_deg=0.0,
            voltage_nominal_kv=bus.voltage_kv,
            compliance=ComplianceStatus.OK,
        )
    # Flujos en líneas
    for branch_id, branch in mock_network.branches.items():
        loading = 85.0 if branch.is_transformer() else 30.0
        compliance = (ComplianceStatus.WARNING
                      if loading > 80 else ComplianceStatus.OK)
        result.branch_flows[branch_id] = BranchFlowResult(
            branch_id=branch_id,
            p_kw=63.0, q_kvar=5.0, s_kva=63.2,
            current_a=200.0, rated_a=240.0,
            loading_pct=loading,
            losses_kw=0.5, losses_kvar=0.3,
            compliance=compliance,
        )
    return result


# =============================================================================
# Tests del generador QML
# =============================================================================
class TestQMLTemplates:

    def test_buses_qml_valid_xml(self):
        qml = qml_templates.qml_buses_compliance()
        assert qml_templates.validate_qml(qml)

    def test_lines_qml_valid_xml(self):
        qml = qml_templates.qml_lines_loading()
        assert qml_templates.validate_qml(qml)

    def test_transformers_qml_valid_xml(self):
        qml = qml_templates.qml_transformers_loading()
        assert qml_templates.validate_qml(qml)

    def test_buses_qml_has_categories(self):
        qml = qml_templates.qml_buses_compliance()
        root = ET.fromstring(qml)
        # Verifica que tenga el renderer y categorías
        renderer = root.find(".//renderer-v2")
        assert renderer is not None
        assert renderer.attrib.get("type") == "categorizedSymbol"
        assert renderer.attrib.get("attr") == "compliance"
        categories = root.findall(".//category")
        assert len(categories) >= 3   # ok, warning, violation

    def test_lines_qml_has_ranges(self):
        qml = qml_templates.qml_lines_loading()
        root = ET.fromstring(qml)
        renderer = root.find(".//renderer-v2")
        assert renderer.attrib.get("type") == "graduatedSymbol"
        assert renderer.attrib.get("attr") == "loading_pct"
        ranges = root.findall(".//range")
        assert len(ranges) >= 4   # 4 rangos definidos


# =============================================================================
# Tests del QGISResultsWriter
# =============================================================================
class TestQGISResultsWriter:

    def test_write_creates_all_files(self, mock_network, mock_result, tmp_path):
        compliance = ComplianceAnalyzer(ARCERNNR_EC).analyze(mock_result)
        writer = QGISResultsWriter(mock_network, mock_result, compliance)
        files = writer.write(str(tmp_path))

        # Verifica todos los archivos esperados
        expected_keys = [
            "buses_geojson", "buses_qml",
            "lines_geojson", "lines_qml",
            "trafos_geojson", "trafos_qml",
            "loader_script", "readme",
        ]
        for key in expected_keys:
            assert key in files
            assert os.path.exists(files[key])

    def test_buses_geojson_has_results(self, mock_network, mock_result, tmp_path):
        writer = QGISResultsWriter(mock_network, mock_result)
        writer.write(str(tmp_path))

        with open(tmp_path / "postes_resultados.geojson", encoding="utf-8") as f:
            data = json.load(f)

        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == len(mock_network.buses)

        # Cada feature debe tener los campos de resultado
        for feat in data["features"]:
            props = feat["properties"]
            assert "id" in props
            assert "v_pu" in props
            assert "v_drop_pct" in props
            assert "compliance" in props
            assert props["compliance"] in ("ok", "warning", "violation", "unknown")

    def test_lines_geojson_has_loading(self, mock_network, mock_result, tmp_path):
        writer = QGISResultsWriter(mock_network, mock_result)
        writer.write(str(tmp_path))

        with open(tmp_path / "lineas_resultados.geojson", encoding="utf-8") as f:
            data = json.load(f)

        # Solo debe contener líneas (no trafos)
        n_lines = len([b for b in mock_network.branches.values() if b.is_line()])
        assert len(data["features"]) == n_lines

        for feat in data["features"]:
            props = feat["properties"]
            assert "loading_pct" in props
            assert "current_a" in props
            assert "compliance" in props
            assert feat["geometry"]["type"] == "LineString"

    def test_transformers_geojson_separate(
        self, mock_network, mock_result, tmp_path,
    ):
        writer = QGISResultsWriter(mock_network, mock_result)
        writer.write(str(tmp_path))

        with open(
            tmp_path / "transformadores_resultados.geojson", encoding="utf-8"
        ) as f:
            data = json.load(f)

        n_trafos = len(mock_network.transformers())
        assert len(data["features"]) == n_trafos

        for feat in data["features"]:
            props = feat["properties"]
            assert "kva" in props
            assert "kv_primary" in props
            assert "kv_secondary" in props
            assert feat["geometry"]["type"] == "Point"

    def test_qml_files_are_valid_xml(self, mock_network, mock_result, tmp_path):
        writer = QGISResultsWriter(mock_network, mock_result)
        writer.write(str(tmp_path))

        for qml_name in (
            "postes_resultados.qml",
            "lineas_resultados.qml",
            "transformadores_resultados.qml",
        ):
            qml_path = tmp_path / qml_name
            assert qml_path.exists()
            # Validar como XML
            ET.parse(str(qml_path))

    def test_loader_script_is_python(self, mock_network, mock_result, tmp_path):
        writer = QGISResultsWriter(mock_network, mock_result)
        writer.write(str(tmp_path))

        script_path = tmp_path / "cargar_en_qgis.py"
        assert script_path.exists()
        content = script_path.read_text(encoding="utf-8")
        # Verificar que contiene los imports de QGIS
        assert "from qgis.core import" in content
        assert "QgsVectorLayer" in content
        assert "QgsProject" in content

    def test_readme_includes_summary(self, mock_network, mock_result, tmp_path):
        compliance = ComplianceAnalyzer(ARCERNNR_EC).analyze(mock_result)
        writer = QGISResultsWriter(mock_network, mock_result, compliance)
        writer.write(str(tmp_path))

        readme = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "Resultados redes_engine" in readme
        assert "Pérdidas técnicas" in readme

    def test_qml_filename_matches_geojson(self, mock_network, mock_result, tmp_path):
        """QGIS aplica el .qml automáticamente si tiene mismo nombre base
        que el .geojson. Verificamos ese requisito."""
        writer = QGISResultsWriter(mock_network, mock_result)
        writer.write(str(tmp_path))

        for stem in (
            "postes_resultados",
            "lineas_resultados",
            "transformadores_resultados",
        ):
            assert (tmp_path / f"{stem}.geojson").exists()
            assert (tmp_path / f"{stem}.qml").exists()


# =============================================================================
# Test integral
# =============================================================================
opendss = pytest.importorskip(
    "opendssdirect",
    reason="opendssdirect no instalado",
)


class TestVisualPipelineEndToEnd:

    def test_full_pipeline_generates_qgis_artifacts(self, tmp_path):
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        from redes_engine.io.opendss_solver import OpenDSSSolver

        net = build_urbanizacion_pastaza()
        with OpenDSSSolver(net) as solver:
            assert solver.solve()
            result = solver.collect_results()

        compliance = ComplianceAnalyzer(ARCERNNR_EC).analyze(result)

        writer = QGISResultsWriter(net, result, compliance)
        files = writer.write(str(tmp_path))

        # Los 3 GeoJSON existen y son JSON válido
        for stem in ("postes", "lineas", "transformadores"):
            path = tmp_path / f"{stem}_resultados.geojson"
            assert path.exists()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["type"] == "FeatureCollection"

        # Los 3 QML existen y son XML válido
        for stem in ("postes", "lineas", "transformadores"):
            qml_path = tmp_path / f"{stem}_resultados.qml"
            assert qml_path.exists()
            ET.parse(str(qml_path))   # no lanza ParseError
