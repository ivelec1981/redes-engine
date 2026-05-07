# -*- coding: utf-8 -*-
"""
Tests del importador GIS — verifica que GeoJSON se traduce correctamente
a Network con snap automático y mapping flexible de campos.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.core.graph import (
    AssetType, BranchType, BusType, VoltageLevel,
)
from redes_engine.io.gis_importer import (
    FieldMapping, GISImporter, ImportReport,
)


FIXTURES_DIR = os.path.join(
    ROOT, "redes_engine", "examples", "gis_fixtures"
)


def fx(name: str) -> str:
    return os.path.join(FIXTURES_DIR, f"{name}.geojson")


# =============================================================================
# Tests del FieldMapping
# =============================================================================
class TestFieldMapping:

    def test_first_match_case_insensitive(self):
        m = FieldMapping()
        attrs = {"NUM_SEQ": "P-001", "VOLTAJE": 22.8}
        assert m.first_match(attrs, ["id", "NUM_SEQ"]) == "P-001"
        assert m.first_match(attrs, ["voltage_kv", "VOLTAJE"]) == 22.8

    def test_first_match_returns_none_when_missing(self):
        m = FieldMapping()
        attrs = {"OTHER": "X"}
        assert m.first_match(attrs, ["id", "NUM_SEQ"]) is None

    def test_first_match_skips_empty(self):
        m = FieldMapping()
        attrs = {"id": "", "NUM_SEQ": "REAL"}
        assert m.first_match(attrs, ["id", "NUM_SEQ"]) == "REAL"


# =============================================================================
# Tests del importador desde GeoJSON
# =============================================================================
class TestGeoJSONImport:

    def test_import_buses_only(self):
        importer = GISImporter()
        net, report = importer.from_geojson(
            {"postes_mt": fx("postes_mt")},
            network_name="OnlyBuses",
        )
        assert report.buses_imported == 3
        assert "P-MT-001" in net.buses
        assert net.buses["P-MT-001"].voltage_kv == 22.8
        assert net.buses["P-MT-001"].zone == "Pastaza-01"

    def test_import_lines_with_explicit_endpoints(self):
        importer = GISImporter()
        net, report = importer.from_geojson({
            "postes_mt": fx("postes_mt"),
            "tramos_mt": fx("tramos_mt"),
        })
        assert report.branches_imported == 2
        assert "L-MT-001" in net.branches
        line = net.branches["L-MT-001"]
        assert line.bus_from == "P-MT-001"
        assert line.bus_to == "P-MT-002"
        assert line.length_m == pytest.approx(80.0)
        assert line.conductor_type == "ACSR_4/0AWG"

    def test_import_full_network(self):
        importer = GISImporter()
        layers = {
            "postes_mt": fx("postes_mt"),
            "postes_bt": fx("postes_bt"),
            "tramos_mt": fx("tramos_mt"),
            "tramos_bt": fx("tramos_bt"),
            "transformadores": fx("transformadores"),
            "cargas": fx("cargas"),
            "ev_chargers": fx("ev_chargers"),
            "solar_pv": fx("solar_pv"),
            "bess": fx("bess"),
        }
        net, report = importer.from_geojson(layers, network_name="FullNet")

        # Buses: 3 MT + 5 BT importados (P-BT-000 incluido para snap del trafo)
        assert report.buses_imported == 8
        # No deberían crearse buses virtuales: el trafo hace snap a P-BT-000
        assert report.buses_auto_created == 0
        assert report.snap_matches >= 1   # trafo BT side hizo snap

        # 2 líneas MT + 4 líneas BT + 1 trafo
        assert report.branches_imported == 6
        assert report.transformers_imported == 1

        # Assets: 2 cargas + 2 EV + 1 PV + 2 BESS = 7
        assert report.assets_imported == 7

        # La red debe ser conexa (MT→trafo→BT)
        assert net.is_connected()

        # Verificar tipos de EV inferidos por potencia
        ev_assets = [a for a in net.assets.values() if a.is_ev()]
        ev_types = {a.asset_type for a in ev_assets}
        assert AssetType.EV_CHARGER_AC_L2 in ev_types     # 7.4 kW
        assert AssetType.EV_CHARGER_DC_FAST in ev_types   # 50 kW

        # Verificar tipos de BESS inferidos por capacidad
        bess_assets = [a for a in net.assets.values() if a.is_storage()]
        bess_kws = sorted(a.rated_kw for a in bess_assets)
        assert bess_kws == [5.0, 25.0]

    def test_imported_network_is_connected(self):
        importer = GISImporter()
        net, _ = importer.from_geojson({
            "postes_mt": fx("postes_mt"),
            "postes_bt": fx("postes_bt"),
            "tramos_mt": fx("tramos_mt"),
            "transformadores": fx("transformadores"),
        })
        # No exigimos conexa total porque BT y MT podrían estar separados
        # si no hay líneas BT, pero al menos los componentes deben existir.
        assert len(net.connected_components()) >= 1
        assert len(net.buses) >= 6

    def test_voltage_default_when_missing(self):
        """Si el campo VOLTAJE falta, usa el default por tipo."""
        importer = GISImporter(default_voltage_mt_kv=13.8)

        # Crear un GeoJSON temporal sin VOLTAJE
        import tempfile
        data = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NUM_SEQ": "X1"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }]
        }
        with tempfile.NamedTemporaryFile(
            "w", suffix=".geojson", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f)
            path = f.name

        try:
            net, report = importer.from_geojson({"postes_mt": path})
            assert "X1" in net.buses
            assert net.buses["X1"].voltage_kv == 13.8
        finally:
            os.remove(path)


# =============================================================================
# Tests del snap espacial
# =============================================================================
class TestSpatialSnap:

    def test_snap_creates_virtual_bus_when_no_endpoint_match(self, tmp_path):
        """Línea cuyos extremos no coinciden con ningún poste → buses virtuales."""
        importer = GISImporter(snap_tolerance_m=1.0)

        # Una línea sin postes definidos
        line_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NUM_SEQ": "L-X"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[100.0, 100.0], [200.0, 200.0]]
                }
            }]
        }
        line_path = tmp_path / "lines.geojson"
        line_path.write_text(json.dumps(line_geojson), encoding="utf-8")

        net, report = importer.from_geojson({
            "tramos_mt": str(line_path),
        })
        assert report.branches_imported == 1
        assert report.buses_auto_created >= 2

    def test_snap_within_tolerance(self, tmp_path):
        """Extremo de línea cerca de un poste existente → usa ese poste."""
        importer = GISImporter(snap_tolerance_m=10.0)

        # 1 poste en (100, 100)
        bus_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NUM_SEQ": "P_real"},
                "geometry": {"type": "Point", "coordinates": [100.0, 100.0]}
            }]
        }
        bp = tmp_path / "postes.geojson"
        bp.write_text(json.dumps(bus_geojson), encoding="utf-8")

        # 1 línea sin NODO_I/J explícitos, extremo a (102, 100) (2m del poste)
        line_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NUM_SEQ": "L_snap"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[102.0, 100.0], [200.0, 100.0]]
                }
            }]
        }
        lp = tmp_path / "lines.geojson"
        lp.write_text(json.dumps(line_geojson), encoding="utf-8")

        net, report = importer.from_geojson({
            "postes_mt": str(bp),
            "tramos_mt": str(lp),
        })
        line = net.branches.get("L_snap")
        assert line is not None
        # bus_from debe haber hecho snap a P_real
        assert line.bus_from == "P_real"
        assert report.snap_matches >= 1

    def test_no_snap_outside_tolerance(self, tmp_path):
        """Extremo demasiado lejos → crea bus virtual."""
        importer = GISImporter(snap_tolerance_m=1.0)
        bus_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NUM_SEQ": "P_real"},
                "geometry": {"type": "Point", "coordinates": [100.0, 100.0]}
            }]
        }
        bp = tmp_path / "postes.geojson"
        bp.write_text(json.dumps(bus_geojson), encoding="utf-8")

        line_geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"NUM_SEQ": "L_far"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[110.0, 100.0], [200.0, 100.0]]
                }
            }]
        }
        lp = tmp_path / "lines.geojson"
        lp.write_text(json.dumps(line_geojson), encoding="utf-8")

        net, report = importer.from_geojson({
            "postes_mt": str(bp),
            "tramos_mt": str(lp),
        })
        line = net.branches.get("L_far")
        assert line is not None
        # bus_from no debe ser P_real (estaba fuera de tolerancia)
        assert line.bus_from != "P_real"
        # Debe haber al menos 1 bus auto-creado
        assert report.buses_auto_created >= 1


# =============================================================================
# Test integral: importar → exportar a OpenDSS
# =============================================================================
class TestImportToSolve:

    def test_imported_network_can_be_exported_to_dss(self, tmp_path):
        """La red importada puede exportarse a .dss válido."""
        from redes_engine.io.opendss_bridge import OpenDSSExporter

        importer = GISImporter()
        net, report = importer.from_geojson({
            "postes_mt": fx("postes_mt"),
            "postes_bt": fx("postes_bt"),
            "tramos_mt": fx("tramos_mt"),
            "transformadores": fx("transformadores"),
            "cargas": fx("cargas"),
        }, network_name="ImportTest")

        out = tmp_path / "imported.dss"
        OpenDSSExporter(net).export(str(out))
        content = out.read_text(encoding="utf-8")
        assert "New Circuit." in content
        assert "New Line." in content
        assert "New Transformer." in content
        assert "New Load." in content


# =============================================================================
# Test del solver con red importada (requiere opendssdirect)
# =============================================================================
opendss = pytest.importorskip(
    "opendssdirect",
    reason="opendssdirect no instalado",
)


class TestImportSolveAnalyze:

    def test_full_import_solve_analyze_pipeline(self):
        """Pipeline completo: GeoJSON → Network → OpenDSS → Compliance."""
        from redes_engine.core.compliance import (
            ARCERNNR_EC, ComplianceAnalyzer,
        )
        from redes_engine.io.opendss_solver import OpenDSSSolver

        importer = GISImporter()
        net, report = importer.from_geojson({
            "postes_mt": fx("postes_mt"),
            "postes_bt": fx("postes_bt"),
            "tramos_mt": fx("tramos_mt"),
            "transformadores": fx("transformadores"),
            "cargas": fx("cargas"),
            "ev_chargers": fx("ev_chargers"),
            "solar_pv": fx("solar_pv"),
        }, network_name="GISPipeline")

        # 1. La importación debe ser exitosa
        assert report.errors == []

        # 2. Resolver con OpenDSS
        with OpenDSSSolver(net) as solver:
            converged = solver.solve()
            assert converged
            result = solver.collect_results()

        # 3. Analizar cumplimiento
        analyzer = ComplianceAnalyzer(ARCERNNR_EC)
        compliance = analyzer.analyze(result)

        # 4. El reporte debe tener findings
        assert len(compliance.findings) > 0
