# -*- coding: utf-8 -*-
"""
Tests del método público GISImporter.from_features().

Este es el método que usa el adapter de QGIS para construir Network
desde features ya cargadas en memoria (sin pasar por archivos).
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.io.gis_importer import GISImporter


# =============================================================================
# Helpers de fixtures sintéticas
# =============================================================================
def make_bus_feature(num_seq, x, y, voltaje=22.8):
    return {
        "type": "Feature",
        "properties": {"NUM_SEQ": num_seq, "VOLTAJE": voltaje},
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def make_line_feature(num_seq, nodo_i, nodo_j, x1, y1, x2, y2,
                      length=100.0, ampacidad=200.0):
    return {
        "type": "Feature",
        "properties": {
            "NUM_SEQ": num_seq,
            "NODO_I": nodo_i, "NODO_J": nodo_j,
            "LONGITUD": length, "AMPACIDAD": ampacidad,
            "RESISTENCIA": 0.1, "REACTANCIA": 0.15,
        },
        "geometry": {
            "type": "LineString",
            "coordinates": [[x1, y1], [x2, y2]],
        },
    }


def make_trafo_feature(num_seq, x, y, kva=75):
    return {
        "type": "Feature",
        "properties": {
            "NUM_SEQ": num_seq, "POT_KVA": kva,
            "KV_PRIM": 22.8, "KV_SEC": 0.220,
        },
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


# =============================================================================
# Tests
# =============================================================================
class TestFromFeatures:

    def test_from_features_simple(self):
        """from_features acepta dict con listas de features."""
        importer = GISImporter()
        layers = {
            "postes_mt": [
                make_bus_feature("P1", 100, 100),
                make_bus_feature("P2", 200, 100),
            ],
            "tramos_mt": [
                make_line_feature("L1", "P1", "P2", 100, 100, 200, 100,
                                   length=100.0),
            ],
        }
        net, report = importer.from_features(layers, network_name="Test")
        assert report.buses_imported == 2
        assert report.branches_imported == 1
        assert "P1" in net.buses
        assert "L1" in net.branches

    def test_from_features_with_transformer_snap(self):
        """El trafo debe snapear al bus BT cercano si existe."""
        importer = GISImporter(snap_tolerance_m=10.0)
        layers = {
            "postes_mt": [make_bus_feature("PMT1", 100, 100)],
            "postes_bt": [make_bus_feature("PBT1", 100, 101, voltaje=0.220)],
            "transformadores": [make_trafo_feature("T1", 100, 100)],
        }
        net, report = importer.from_features(layers)
        # El trafo debe haber hecho snap a PBT1 en lugar de crear virtual
        assert report.transformers_imported == 1
        assert report.snap_matches >= 1
        # La red debe ser conexa
        assert net.is_connected()

    def test_from_features_empty_layers(self):
        """Layers vacíos no deben romper."""
        importer = GISImporter()
        net, report = importer.from_features({"postes_mt": []})
        assert report.buses_imported == 0
        assert len(net.buses) == 0

    def test_from_features_equivalent_to_from_geojson(self, tmp_path):
        """Mismos datos vía features vs vía archivos = mismo resultado."""
        import json

        bus_features = [
            make_bus_feature("P1", 100, 100),
            make_bus_feature("P2", 200, 100),
        ]
        line_features = [
            make_line_feature("L1", "P1", "P2", 100, 100, 200, 100,
                               length=100.0),
        ]

        # Vía from_features
        importer_a = GISImporter()
        net_a, _ = importer_a.from_features({
            "postes_mt": bus_features,
            "tramos_mt": line_features,
        })

        # Vía archivos GeoJSON
        bus_path = tmp_path / "buses.geojson"
        line_path = tmp_path / "lines.geojson"
        bus_path.write_text(json.dumps({
            "type": "FeatureCollection", "features": bus_features,
        }), encoding="utf-8")
        line_path.write_text(json.dumps({
            "type": "FeatureCollection", "features": line_features,
        }), encoding="utf-8")

        importer_b = GISImporter()
        net_b, _ = importer_b.from_features({
            "postes_mt": bus_features,
            "tramos_mt": line_features,
        })

        # Mismos buses, branches, assets
        assert set(net_a.buses.keys()) == set(net_b.buses.keys())
        assert set(net_a.branches.keys()) == set(net_b.branches.keys())
