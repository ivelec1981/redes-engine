# -*- coding: utf-8 -*-
"""
Análisis de Host Capacity sobre la red urbanización Pastaza.

Responde preguntas como:
    "¿Cuánto PV puedo permitir al cliente del medidor Bus_010
     sin causar problemas de tensión o sobrecarga?"

Algoritmo:
    1. Tomar la red base
    2. Para cada bus:
        a) Bisección sobre la potencia PV inyectable
        b) Bisección sobre la potencia de carga adicional
    3. Devolver mapa de capacidad por bus + factor limitante

Output:
    - Tabla ranking
    - GeoJSON + QML para visualizar en QGIS
"""

import os
import sys
import time

from ..hosting import (
    HostingCapacityAnalyzer,
    hosting_ranking_table,
    write_hosting_geojson,
)
from ..timeseries import ProfileLibrary
from .urbanizacion_mixta import build_urbanizacion_pastaza

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "hosting_output")


def run(n_critical_hours: int = 50, max_kw: float = 200.0) -> int:
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│  HOST CAPACITY ANALYSIS                                      │")
    print("│  ¿Cuánto VE/PV puede soportar cada bus de la red?            │")
    print("└─────────────────────────────────────────────────────────────┘\n")

    # ── 1. Cargar red base ────────────────────────────────────────────
    net = build_urbanizacion_pastaza()
    print(f"📐 Red: {net.name} — {len(net.buses)} buses, "
          f"{len(net.branches)} branches\n")

    # ── 2. Cargar perfiles ────────────────────────────────────────────
    profiles = ProfileLibrary.ecuador_default(seed=42)

    # ── 3. Configurar analizador ──────────────────────────────────────
    analyzer = HostingCapacityAnalyzer(
        network=net, profiles=profiles,
        vmin_pu=0.92,        # caída máxima 8% (BT)
        vmax_pu=1.05,        # subida máxima 5% (regulación PV)
        line_loading_max=100.0,
        trafo_loading_max=100.0,
    )

    # ── 4. Ejecutar análisis ──────────────────────────────────────────
    print(f"⚙ Analizando {len(net.buses)} buses...")
    print(f"   Bisección PV + Carga, {n_critical_hours} horas críticas")
    print(f"   Rango: 0 — {max_kw} kW\n")

    t_start = time.time()
    results = analyzer.analyze_all(
        include_pv=True, include_load=True,
        n_critical_hours=n_critical_hours,
        tolerance_kw=2.0,
        max_kw=max_kw,
    )
    elapsed = time.time() - t_start

    # ── 5. Reporte ────────────────────────────────────────────────────
    print(results.summary())
    print(hosting_ranking_table(results, n=20, sort_by="pv"))
    print()
    print(hosting_ranking_table(results, n=20, sort_by="load"))

    # ── 6. Generar capas QGIS ─────────────────────────────────────────
    print("\n" + "═" * 65)
    print("  🗺  Generando capas GeoJSON + QML para QGIS...")
    print("═" * 65)
    files = write_hosting_geojson(net, results, OUTPUT_DIR)
    for k, p in files.items():
        size_kb = os.path.getsize(p) / 1024
        print(f"   • {os.path.basename(p):<40} ({size_kb:>5.1f} KB)")

    # ── 7. Insights y recomendaciones ─────────────────────────────────
    print("\n" + "═" * 65)
    print("  📌 INSIGHTS — Lo que estos números significan")
    print("═" * 65)

    best_pv = results.best_pv_buses(3)
    worst_pv = results.worst_pv_buses(3)
    best_load = results.best_load_buses(3)

    print("\n  🟢 BUSES CON MAYOR CAPACIDAD PV (mejores para autorizar nuevos paneles):")
    for b in best_pv:
        print(f"     • {b.bus_id} → hasta {b.pv_hosting_kw:.1f} kW PV "
              f"(limita: {b.pv_limiting_factor.value})")

    print("\n  🔴 BUSES SATURADOS PARA PV (rechazar/limitar nuevas solicitudes):")
    for b in worst_pv:
        print(f"     • {b.bus_id} → solo {b.pv_hosting_kw:.1f} kW disponibles "
              f"(bloqueo: {b.pv_limiting_factor.value} en hora "
              f"{b.pv_limiting_hour})")

    print("\n  🟢 BUSES CON MAYOR CAPACIDAD DE CARGA (ideales para cargadores VE rápidos):")
    for b in best_load:
        print(f"     • {b.bus_id} → hasta {b.load_hosting_kw:.1f} kW carga adicional "
              f"(limita: {b.load_limiting_factor.value})")

    print(f"\n  ⏱ Tiempo total: {elapsed:.1f} s "
          f"para {results.n_iterations_total} iteraciones")
    print("═" * 65)
    print()

    return 0


if __name__ == "__main__":
    # Ajustes: n_critical_hours por defecto 50 (suficiente para un prototipo).
    #   Producción: usar 200+ horas críticas para mayor precisión.
    n_hours = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    max_kw = float(sys.argv[2]) if len(sys.argv) > 2 else 200.0
    sys.exit(run(n_critical_hours=n_hours, max_kw=max_kw))
