# -*- coding: utf-8 -*-
"""
Pipeline visual completo: GIS → Solver → QGIS Layers.

El ciclo cerrado del ingeniero diseñador:
    1. Importar capas QGIS (GeoJSON)
    2. Resolver flujo de potencia con OpenDSS
    3. Evaluar cumplimiento normativo
    4. Generar capas QGIS con resultados + simbología automática
    5. (Opcional) abrir QGIS y arrastrar las capas

El usuario ve un mapa con:
    - Postes coloreados por estado (verde/amarillo/rojo)
    - Líneas con grosor proporcional a la carga
    - Trafos con tamaño según utilización
    - Etiquetas con valores numéricos
"""

import os
import sys

from ..core.compliance import ARCERNNR_EC, ComplianceAnalyzer
from ..io.gis_importer import GISImporter
from ..io.opendss_solver import OpenDSSNotAvailableError, OpenDSSSolver
from ..io.qgis_writer import QGISResultsWriter

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "gis_fixtures")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "qgis_output")


def run() -> int:
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│  PIPELINE VISUAL COMPLETO: GIS → ENGINE → QGIS               │")
    print("└─────────────────────────────────────────────────────────────┘\n")

    # ── 1. Importar desde GIS ────────────────────────────────────────
    print("📂 [1/4] Importando capas GeoJSON...")
    importer = GISImporter()
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
    net, import_report = importer.from_geojson(layers, "ElPastaza_Vis")
    print(f"     ✓ {len(net.buses)} buses, {len(net.branches)} branches, "
          f"{len(net.assets)} assets\n")

    # ── 2. Resolver con OpenDSS ──────────────────────────────────────
    print("⚡ [2/4] Resolviendo flujo de potencia con OpenDSS...")
    try:
        with OpenDSSSolver(net, keep_files=False) as solver:
            converged = solver.solve()
            if not converged:
                print("     ❌ No convergió.")
                return 1
            result = solver.collect_results()
            print(f"     ✓ Convergió en {result.iterations} iteraciones — "
                  f"pérdidas {result.losses_pct:.2f}%\n")
    except OpenDSSNotAvailableError as e:
        print(f"     ⚠ {e}")
        return 2

    # ── 3. Evaluar cumplimiento ──────────────────────────────────────
    print("🛡 [3/4] Evaluando cumplimiento ARCERNNR 002/20...")
    compliance = ComplianceAnalyzer(ARCERNNR_EC).analyze(result)
    print(f"     ✓ Estado: {compliance.overall_status.value.upper()}  |  "
          f"{len(compliance.violations())} violaciones, "
          f"{len(compliance.warnings())} advertencias\n")

    # ── 4. Generar capas QGIS ────────────────────────────────────────
    print("🗺 [4/4] Generando capas QGIS con simbología automática...")
    writer = QGISResultsWriter(net, result, compliance, crs="EPSG:32717")
    files = writer.write(OUTPUT_DIR)

    print(f"     ✓ Salida en: {OUTPUT_DIR}")
    for key, path in files.items():
        size_kb = os.path.getsize(path) / 1024
        print(f"        • {os.path.basename(path):<45} ({size_kb:>5.1f} KB)")

    # ── Cierre ──────────────────────────────────────────────────────
    print("\n" + "═" * 65)
    print("  ✨ LISTO PARA QGIS")
    print("═" * 65)
    print()
    print("  Cómo visualizar:")
    print(f"  1. Abrir QGIS 3.16+")
    print(f"  2. Arrastrar los archivos .geojson al canvas")
    print(f"     (la simbología se aplica automáticamente via .qml)")
    print()
    print("  Alternativamente:")
    print(f"  1. Plugins → Python Console")
    print(f"  2. Ejecutar: exec(open(r'{files['loader_script']}').read())")
    print()
    print("  El usuario verá un mapa con:")
    print("     🟢 Postes verdes → cumplen voltaje normativo")
    print("     🟡 Postes amarillos → cerca del límite (>80%)")
    print("     🔴 Postes rojos → fuera de norma")
    print("     ▬▬ Líneas con grosor proporcional a la carga")
    print("     ■ Trafos con tamaño según % utilización")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(run())
