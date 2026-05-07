# -*- coding: utf-8 -*-
"""
Ejemplo: optimización de despacho 24h sobre la urbanización Pastaza.

Demuestra:
    ✓ Cargar la red de ejemplo
    ✓ Definir tarifa TOU (time-of-use)
    ✓ Asignar tareas de carga a los VE
    ✓ Resolver MILP de dispatch BESS + smart charging VE
    ✓ Imprimir resultados horarios
"""

from ..core.optimization import (
    DispatchOptimizer,
    EVChargingTask,
    TariffSchedule,
    hourly_table,
    print_dispatch_summary,
)
from .urbanizacion_mixta import build_urbanizacion_pastaza


def run() -> None:
    # ── 1. Construir la red ───────────────────────────────────────────
    net = build_urbanizacion_pastaza()
    print(net.summary())

    # ── 2. Definir tarifa TOU (precios típicos Ecuador residencial) ──
    tariff = TariffSchedule(
        buy_price=[
            # 0-5: madrugada (baja: $0.04/kWh)
            0.04, 0.04, 0.04, 0.04, 0.04, 0.04,
            # 6-17: día (media: $0.09/kWh)
            0.09, 0.09, 0.09, 0.09, 0.09, 0.09,
            0.09, 0.09, 0.09, 0.09, 0.09, 0.09,
            # 18-22: punta (alta: $0.20/kWh)
            0.20, 0.20, 0.20, 0.20, 0.20,
            # 23: fin del día (baja)
            0.04,
        ],
        sell_price=[0.05] * 24,   # feed-in tariff fijo
    )

    # ── 3. Crear el optimizador ───────────────────────────────────────
    opt = DispatchOptimizer(
        network=net,
        tariff=tariff,
        grid_import_limit_kw=100.0,   # transformador 75 kVA → ~75 kW útil
        soc_min=0.20,
        soc_max=0.95,
    )

    # ── 4. Definir tareas de carga de VE ──────────────────────────────
    # VE Casa A: necesita 22 kWh, disponible 19:00-06:00
    opt.add_ev_task(EVChargingTask(
        asset_id="EV_010",
        energy_kwh=22.0,
        available_hours=[19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6],
    ))

    # V2G Casa B: requiere mantener 60% SoC al final del día (40 kWh)
    # Nota: este es bidireccional, pero lo tratamos solo como carga aquí
    opt.add_ev_task(EVChargingTask(
        asset_id="V2G_011",
        energy_kwh=15.0,
        available_hours=list(range(17, 24)) + list(range(0, 7)),
    ))

    # Cargador rápido comunal: 80 kWh dispersos durante el día
    opt.add_ev_task(EVChargingTask(
        asset_id="EVDC_006",
        energy_kwh=80.0,
        available_hours=list(range(6, 22)),
    ))

    # ── 5. Resolver ───────────────────────────────────────────────────
    print("\n⚙ Resolviendo despacho óptimo MILP...\n")
    result = opt.solve()

    # ── 6. Reporte ────────────────────────────────────────────────────
    print_dispatch_summary(result)
    print(hourly_table(result))

    # ── 7. Comparar con escenario sin optimización ────────────────────
    cost_naive = _compute_naive_cost(net, tariff, opt)
    print()
    print("=" * 64)
    print(f"  COMPARACIÓN")
    print("=" * 64)
    print(f"  Sin optimización (carga inmediata, BESS pasivo) : "
          f"${cost_naive:,.2f}")
    print(f"  Con optimización MILP (smart dispatch)          : "
          f"${result.objective_cost:,.2f}")
    saving = cost_naive - result.objective_cost
    pct = (saving / cost_naive * 100) if cost_naive > 0 else 0.0
    print(f"  Ahorro diario                                   : "
          f"${saving:,.2f} ({pct:+.1f}%)")
    print(f"  Ahorro anual proyectado                         : "
          f"${saving * 365:,.2f}")
    print("=" * 64)


def _compute_naive_cost(net, tariff, opt):
    """Costo si se cargara todo apenas se conecta y BESS estuviera apagado."""
    cost = 0.0
    for t in range(24):
        load = opt._aggregate_load(t)
        pv = opt._aggregate_pv(t)
        # VE: distribuye su energía uniformemente en su ventana
        ev_t = 0.0
        for v_id, task in opt.ev_tasks.items():
            avail = len(task.available_hours)
            if t in task.available_hours and avail > 0:
                ev_t += task.energy_kwh / avail
        net_grid = load + ev_t - pv
        if net_grid > 0:
            cost += net_grid * tariff.buy_price[t]
        else:
            cost += net_grid * tariff.sell_price[t]
    return cost


if __name__ == "__main__":
    run()
