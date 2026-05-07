# -*- coding: utf-8 -*-
"""
Análisis anual 8760h — Comparación de escenarios 2026 vs 2030.

Demuestra:
    1. Construir red base
    2. Simular año actual (baseline 2026)
    3. Aplicar escenario futuro (25% VE + 20% PV en 2030)
    4. Simular año futuro
    5. Comparar y reportar

Tiempo de ejecución estimado:
    - 168h (1 semana): ~5 segundos
    - 720h (1 mes):    ~20 segundos
    - 8760h (1 año):   ~3-5 minutos
"""

import sys
import time
from copy import deepcopy

from ..timeseries import (
    ProfileLibrary,
    Scenario,
    ScenarioComparison,
    TimeSeriesSolver,
)
from .urbanizacion_mixta import build_urbanizacion_pastaza


def progress_print(current: int, total: int) -> None:
    """Callback de progreso para la consola."""
    pct = 100.0 * current / total
    bar_len = 40
    filled = int(bar_len * current / total)
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stdout.write(f"\r  ⏳ [{bar}] {pct:5.1f}% ({current}/{total} h)")
    sys.stdout.flush()


def run(hours: int = 168) -> int:
    """
    Ejecuta el análisis anual.

    Parameters
    ----------
    hours : int
        Número de horas a simular. Default 168 (1 semana — rápido).
        Use 8760 para análisis anual completo.
    """
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│  ANÁLISIS TEMPORAL 8760h — Comparación de escenarios         │")
    print("│  Baseline 2026  vs  Penetración VE/PV 2030                  │")
    print("└─────────────────────────────────────────────────────────────┘\n")

    profiles = ProfileLibrary.ecuador_default(seed=42)
    print(f"📊 Cargados {len(profiles)} perfiles de la librería Ecuador.\n")

    # ── ESCENARIO 1: Baseline 2026 ───────────────────────────────────
    print("=" * 65)
    print("  ESCENARIO 1: BASELINE 2026")
    print("=" * 65)

    net_2026 = build_urbanizacion_pastaza()
    print(net_2026.summary())

    print(f"\n⏳ Simulando {hours} horas con perfiles realistas...\n")
    t_start = time.time()
    solver_2026 = TimeSeriesSolver(
        network=net_2026,
        profiles=profiles,
        progress_callback=progress_print,
    )
    annual_2026 = solver_2026.run(hours=hours, scenario_name="Baseline 2026")
    elapsed = time.time() - t_start
    print(f"\n  ✓ {annual_2026.n_hours_simulated} horas simuladas en "
          f"{elapsed:.1f} s ({elapsed*1000/max(annual_2026.n_hours_simulated,1):.1f} ms/h)\n")

    print(annual_2026.summary())
    print(annual_2026.violation_table(max_rows=5))
    print(annual_2026.overload_table(max_rows=5))

    # ── ESCENARIO 2: Futuro 2030 con penetración alta ─────────────────
    print("\n" + "=" * 65)
    print("  ESCENARIO 2: 2030 — 50% VE + 30% PV + crecimiento 3%/año")
    print("=" * 65)

    net_2030 = build_urbanizacion_pastaza()
    scenario_2030 = Scenario(
        name="2030 - Alta penetración",
        year=2030, base_year=2026,
        ev_penetration_pct=50.0,
        ev_avg_kwh_per_day=22.0,
        pv_penetration_pct=30.0,
        pv_avg_kwp=5.0,
        bess_grid_capacity_kwh=0.0,   # sin BESS adicional
        base_load_growth_pct_per_year=3.0,
        notes="Política nacional de electromovilidad, sin BESS adicional",
    )
    application = scenario_2030.apply_to_network(net_2030, profiles)
    print(application.summary())
    print(net_2030.summary())

    print(f"\n⏳ Simulando {hours} horas...\n")
    t_start = time.time()
    solver_2030 = TimeSeriesSolver(
        network=net_2030,
        profiles=profiles,
        progress_callback=progress_print,
    )
    annual_2030 = solver_2030.run(hours=hours, scenario_name="2030 Alta penetración")
    elapsed = time.time() - t_start
    print(f"\n  ✓ Simulación completa en {elapsed:.1f} s\n")

    print(annual_2030.summary())
    print(annual_2030.violation_table(max_rows=5))
    print(annual_2030.overload_table(max_rows=5))

    # ── ESCENARIO 3: 2030 con BESS comunitario para mitigar ──────────
    print("\n" + "=" * 65)
    print("  ESCENARIO 3: 2030 — 50% VE + 30% PV + BESS 200 kWh")
    print("=" * 65)

    net_2030_bess = build_urbanizacion_pastaza()
    scenario_2030_bess = Scenario(
        name="2030 con BESS",
        year=2030, base_year=2026,
        ev_penetration_pct=50.0,
        pv_penetration_pct=30.0,
        bess_grid_capacity_kwh=200.0,
        bess_grid_power_kw=80.0,
        base_load_growth_pct_per_year=3.0,
    )
    scenario_2030_bess.apply_to_network(net_2030_bess, profiles, random_seed=42)

    print(f"\n⏳ Simulando {hours} horas...\n")
    t_start = time.time()
    solver_2030_bess = TimeSeriesSolver(
        network=net_2030_bess,
        profiles=profiles,
        progress_callback=progress_print,
    )
    annual_2030_bess = solver_2030_bess.run(
        hours=hours, scenario_name="2030 con BESS"
    )
    print(f"\n  ✓ Simulación completa en {time.time()-t_start:.1f} s\n")

    print(annual_2030_bess.summary())

    # ── COMPARACIÓN ENTRE ESCENARIOS ──────────────────────────────────
    print("\n" + "=" * 65)
    print("  📊 COMPARACIÓN ENTRE ESCENARIOS")
    print("=" * 65)
    print()

    cmp = ScenarioComparison()
    cmp.add(scenario_2030.__class__(name="2026 Baseline", year=2026), annual_2026)
    cmp.add(scenario_2030, annual_2030)
    cmp.add(scenario_2030_bess, annual_2030_bess)
    print(cmp.diff_table())

    # ── DIAGNÓSTICO Y RECOMENDACIONES ─────────────────────────────────
    print("\n" + "=" * 65)
    print("  📌 DIAGNÓSTICO Y RECOMENDACIONES")
    print("=" * 65)

    delta_demand = annual_2030.peak_demand_kw - annual_2026.peak_demand_kw
    delta_losses = annual_2030.losses_pct - annual_2026.losses_pct
    diff_violations = (
        len(annual_2030.buses_with_violation_hours)
        - len(annual_2026.buses_with_violation_hours)
    )

    print(f"\n  Crecimiento de demanda pico  : +{delta_demand:.2f} kW "
          f"(+{100*delta_demand/max(annual_2026.peak_demand_kw,1e-3):.1f}%)")
    print(f"  Cambio en pérdidas técnicas  : {delta_losses:+.2f} pp")
    print(f"  Buses adicionales en violación: {diff_violations:+d}")

    if delta_violations := (
        len(annual_2030.buses_with_violation_hours)
        - len(annual_2030_bess.buses_with_violation_hours)
    ) > 0:
        print(f"\n  ✅ El BESS de 200 kWh redujo en {delta_violations} "
              "el número de buses con violaciones de voltaje.")

    if annual_2030.peak_transformer_loading_pct > 100.0:
        print(f"\n  ⚠ El trafo {annual_2030.peak_transformer_id} "
              f"alcanza {annual_2030.peak_transformer_loading_pct:.1f}% en 2030.")
        print(f"  → Recomendación: aumentar capacidad o agregar trafo gemelo.")

    return 0


if __name__ == "__main__":
    # Por defecto simulamos 1 semana (168h). Pasar argumento para más horas:
    #   python -m redes_engine.examples.analisis_anual 8760
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 168
    sys.exit(run(hours=hours))
