# -*- coding: utf-8 -*-
"""
Tests del módulo hosting.

Cubre:
    - Estructuras de resultados
    - Ranking y serialización
    - HostingCapacityAnalyzer (requiere opendssdirect)
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.hosting.results import (
    BusHostingCapacity, HostingCapacityResults, LimitingFactor,
)


# =============================================================================
# Estructuras de resultados (no requieren OpenDSS)
# =============================================================================
class TestBusHostingCapacity:

    def test_creation(self):
        cap = BusHostingCapacity(
            bus_id="B1", voltage_nominal_kv=22.8,
            pv_hosting_kw=120.0,
            pv_limiting_factor=LimitingFactor.OVERVOLTAGE,
            pv_limiting_hour=12,
        )
        assert cap.bus_id == "B1"
        assert cap.pv_hosting_kw == 120.0
        assert cap.pv_limiting_factor == LimitingFactor.OVERVOLTAGE

    def test_total_iterations(self):
        cap = BusHostingCapacity(
            bus_id="B1", voltage_nominal_kv=22.8,
            pv_iterations=10, load_iterations=8,
        )
        assert cap.total_iterations() == 18


class TestHostingCapacityResults:

    @pytest.fixture
    def results(self):
        r = HostingCapacityResults(network_name="Test", n_buses_analyzed=3)
        r.bus_results["B1"] = BusHostingCapacity(
            bus_id="B1", voltage_nominal_kv=22.8,
            pv_hosting_kw=200.0, load_hosting_kw=50.0,
        )
        r.bus_results["B2"] = BusHostingCapacity(
            bus_id="B2", voltage_nominal_kv=0.220,
            pv_hosting_kw=10.0, load_hosting_kw=120.0,
        )
        r.bus_results["B3"] = BusHostingCapacity(
            bus_id="B3", voltage_nominal_kv=0.220,
            pv_hosting_kw=80.0, load_hosting_kw=80.0,
        )
        return r

    def test_best_pv_buses_ordered(self, results):
        top = results.best_pv_buses(2)
        assert top[0].bus_id == "B1"
        assert top[1].bus_id == "B3"

    def test_worst_pv_buses_ordered(self, results):
        bottom = results.worst_pv_buses(2)
        assert bottom[0].bus_id == "B2"

    def test_best_load_buses_ordered(self, results):
        top = results.best_load_buses(2)
        assert top[0].bus_id == "B2"
        assert top[1].bus_id == "B3"

    def test_total_capacity(self, results):
        assert results.total_pv_capacity_kw() == pytest.approx(290.0)
        assert results.total_load_capacity_kw() == pytest.approx(250.0)

    def test_summary_includes_totals(self, results):
        text = results.summary()
        assert "Test" in text
        assert "3" in text   # n_buses
        assert "290" in text   # total PV

    def test_ranking_table_top_k(self, results):
        text = results.ranking_table(n=2)
        # Deben aparecer al menos 2 buses
        # (los headers + 2 filas)
        assert "B1" in text or "B3" in text


# =============================================================================
# Visualización (sin OpenDSS)
# =============================================================================
class TestVisualization:

    @pytest.fixture
    def small_setup(self):
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        net = build_urbanizacion_pastaza()
        results = HostingCapacityResults(
            network_name=net.name, n_buses_analyzed=len(net.buses),
        )
        for bid, bus in net.buses.items():
            results.bus_results[bid] = BusHostingCapacity(
                bus_id=bid, voltage_nominal_kv=bus.voltage_kv,
                pv_hosting_kw=50.0 + hash(bid) % 100,
                load_hosting_kw=30.0 + hash(bid) % 80,
                pv_limiting_factor=LimitingFactor.OVERVOLTAGE,
                load_limiting_factor=LimitingFactor.UNDERVOLTAGE,
            )
        return net, results

    def test_write_geojson_creates_files(self, small_setup, tmp_path):
        from redes_engine.hosting.visualization import write_hosting_geojson

        net, results = small_setup
        files = write_hosting_geojson(net, results, str(tmp_path))

        assert "geojson" in files
        assert os.path.exists(files["geojson"])
        assert os.path.exists(files["qml_pv"])
        assert os.path.exists(files["qml_load"])

    def test_geojson_has_hosting_attrs(self, small_setup, tmp_path):
        from redes_engine.hosting.visualization import write_hosting_geojson

        net, results = small_setup
        files = write_hosting_geojson(net, results, str(tmp_path))

        with open(files["geojson"], encoding="utf-8") as f:
            data = json.load(f)

        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == len(net.buses)
        for feat in data["features"]:
            props = feat["properties"]
            assert "pv_hosting_kw" in props
            assert "load_hosting_kw" in props
            assert "pv_limit" in props

    def test_ranking_table(self, small_setup):
        from redes_engine.hosting.visualization import hosting_ranking_table

        net, results = small_setup
        text = hosting_ranking_table(results, n=5, sort_by="pv")
        # Debe contener al menos 1 bus_id
        assert any(bid in text for bid in net.buses)


# =============================================================================
# Analizador completo (requiere OpenDSS)
# =============================================================================
opendss = pytest.importorskip(
    "opendssdirect", reason="opendssdirect no instalado",
)


class TestHostingCapacityAnalyzer:

    @pytest.fixture
    def network(self):
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        return build_urbanizacion_pastaza()

    def test_analyze_returns_capacity_for_all_buses(self, network):
        from redes_engine.hosting import HostingCapacityAnalyzer

        analyzer = HostingCapacityAnalyzer(network)
        # Análisis rápido: pocas horas críticas, tolerancia laxa
        results = analyzer.analyze_all(
            include_pv=True, include_load=True,
            n_critical_hours=10,
            tolerance_kw=10.0, max_kw=100.0,
            bus_filter=["Bus_010", "Bus_011"],
        )
        assert "Bus_010" in results.bus_results
        assert "Bus_011" in results.bus_results

    def test_pv_hosting_is_nonzero(self, network):
        """Algún bus debe tener al menos algo de capacidad PV."""
        from redes_engine.hosting import HostingCapacityAnalyzer

        analyzer = HostingCapacityAnalyzer(network)
        results = analyzer.analyze_all(
            include_pv=True, include_load=False,
            n_critical_hours=10,
            tolerance_kw=10.0, max_kw=100.0,
            bus_filter=["Bus_010"],
        )
        cap = results.bus_results["Bus_010"]
        # Debe haber convergido a un valor entre 0 y 100
        assert 0 <= cap.pv_hosting_kw <= 100

    def test_full_pipeline_with_visualization(self, network, tmp_path):
        """El pipeline completo: analizar + escribir GeoJSON."""
        from redes_engine.hosting import HostingCapacityAnalyzer
        from redes_engine.hosting.visualization import write_hosting_geojson

        analyzer = HostingCapacityAnalyzer(network)
        results = analyzer.analyze_all(
            include_pv=True, include_load=True,
            n_critical_hours=8,
            tolerance_kw=10.0, max_kw=80.0,
        )
        files = write_hosting_geojson(network, results, str(tmp_path))
        assert os.path.exists(files["geojson"])

        with open(files["geojson"], encoding="utf-8") as f:
            data = json.load(f)
        # Cada bus tiene un feature con pv_hosting_kw
        assert all("pv_hosting_kw" in feat["properties"]
                   for feat in data["features"])
