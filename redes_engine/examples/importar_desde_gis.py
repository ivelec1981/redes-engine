# -*- coding: utf-8 -*-
"""
Pipeline completo: GeoJSON (QGIS) → Network → OpenDSS → Compliance Report.

Demuestra el flujo de trabajo real del ingeniero diseñador:
    1. Tiene capas QGIS exportadas como GeoJSON
       (postes, tramos, trafos, cargas, VEs, PV, BESS)
    2. redes_engine las importa con snap automático
    3. Resuelve flujo de potencia con OpenDSS real
    4. Evalúa cumplimiento ARCERNNR
    5. Genera reporte ejecutivo + sugerencias de acción
"""

import os
import sys

from ..core.compliance import ARCERNNR_EC, ComplianceAnalyzer
from ..core.results import ComplianceStatus
from ..io.gis_importer import FieldMapping, GISImporter
from ..io.opendss_solver import OpenDSSNotAvailableError, OpenDSSSolver

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "gis_fixtures")


def run() -> int:
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│  PIPELINE GIS → SIMULATION → COMPLIANCE                     │")
    print("│  Caso real: ingeniero diseñador trabaja en QGIS y exporta   │")
    print("│  capas a GeoJSON. redes_engine cierra el ciclo completo.    │")
    print("└─────────────────────────────────────────────────────────────┘\n")

    # ── 1. Mapeo de campos (convención EEQ Ecuador) ───────────────────
    # El usuario puede ajustar esto si su empresa usa otros nombres
    mapping = FieldMapping()  # ya viene con defaults razonables EC
    importer = GISImporter(
        mapping=mapping,
        snap_tolerance_m=5.0,
        default_voltage_mt_kv=22.8,
        default_voltage_bt_kv=0.220,
    )

    # ── 2. Definir las capas GeoJSON exportadas desde QGIS ───────────
    layers = {
        "postes_mt":       os.path.join(FIXTURES_DIR, "postes_mt.geojson"),
        "postes_bt":       os.path.join(FIXTURES_DIR, "postes_bt.geojson"),
        "tramos_mt":       os.path.join(FIXTURES_DIR, "tramos_mt.geojson"),
        "tramos_bt":       os.path.join(FIXTURES_DIR, "tramos_bt.geojson"),
        "transformadores": os.path.join(FIXTURES_DIR, "transformadores.geojson"),
        "cargas":          os.path.join(FIXTURES_DIR, "cargas.geojson"),
        "ev_chargers":     os.path.join(FIXTURES_DIR, "ev_chargers.geojson"),
        "solar_pv":        os.path.join(FIXTURES_DIR, "solar_pv.geojson"),
        "bess":            os.path.join(FIXTURES_DIR, "bess.geojson"),
    }

    print("📂 Capas GeoJSON detectadas:")
    for layer_type, path in layers.items():
        size_kb = os.path.getsize(path) / 1024
        print(f"   • {layer_type:<18}: {os.path.basename(path)} ({size_kb:.1f} KB)")
    print()

    # ── 3. Importar al modelo Network ─────────────────────────────────
    print("⚙ Importando capas GIS al grafo unificado...\n")
    net, report = importer.from_geojson(layers, network_name="ElPastaza_GIS")
    print(report.summary())
    print()

    if report.errors:
        print("❌ Importación falló con errores. Abortando.")
        return 1

    print(net.summary())
    print()

    # ── 4. Resolver con OpenDSS ───────────────────────────────────────
    print("⚡ Resolviendo flujo de potencia con OpenDSS...\n")
    try:
        with OpenDSSSolver(net, keep_files=True) as solver:
            converged = solver.solve()
            if not converged:
                print("❌ No convergió.")
                return 2
            result = solver.collect_results()
            print(result.summary())
            print(result.voltage_table())
            print(result.branch_table())
    except OpenDSSNotAvailableError as e:
        print(f"⚠ {e}")
        print("   (Instale opendssdirect para análisis completo)")
        return 0

    # ── 5. Análisis normativo ─────────────────────────────────────────
    print("\n🛡 Evaluando cumplimiento normativo (ARCERNNR 002/20)...\n")
    analyzer = ComplianceAnalyzer(ARCERNNR_EC)
    compliance = analyzer.analyze(result)
    print(compliance.summary())

    # ── 6. Decisión y sugerencias ─────────────────────────────────────
    print()
    if compliance.overall_status == ComplianceStatus.VIOLATION:
        print("📌 DECISIÓN: La red NO cumple normativa.")
        print("\n   ACCIONES RECOMENDADAS:")
        for v in compliance.violations():
            if v.category == "voltaje":
                print(f"   • {v.element_id}: aumentar calibre del conductor "
                      f"de la línea aguas arriba o instalar regulador de tensión")
            elif v.category == "ampacidad":
                print(f"   • {v.element_id}: reemplazar elemento por uno de "
                      f"mayor capacidad (carga actual {v.actual_value:.1f}%)")
            elif v.category == "perdidas":
                print(f"   • Sistema: pérdidas {v.actual_value:.2f}% > "
                      f"objetivo {v.limit_value}%. Considere reubicar trafos "
                      f"o agregar bancos de capacitores.")
        return 1
    elif compliance.overall_status == ComplianceStatus.WARNING:
        print("📌 DECISIÓN: La red cumple normativa, pero hay puntos a vigilar.")
        for w in compliance.warnings():
            print(f"   🟡 {w.element_id}: {w.message}")
        return 0
    else:
        print("📌 DECISIÓN: ✅ La red cumple plenamente la normativa ARCERNNR.")
        return 0


if __name__ == "__main__":
    sys.exit(run())
