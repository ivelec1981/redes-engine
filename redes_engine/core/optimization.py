# -*- coding: utf-8 -*-
"""
redes_engine.core.optimization
================================

Optimización MILP del despacho de BESS y carga inteligente de VE.

FORMULACIÓN MATEMÁTICA
======================

Conjuntos
---------
    T = {0, 1, ..., 23}         horizonte horario (24h)
    B = conjunto de BESS        (almacenamiento estacionario)
    V = conjunto de cargadores VE (controlables)
    G = conjunto de generadores PV
    L = conjunto de cargas no controlables

Parámetros
----------
    π_buy[t]      precio de compra de energía a la red ($/kWh) en hora t
    π_sell[t]     precio de venta (feed-in tariff) en hora t
    P_load[l,t]   demanda no controlable de la carga l en t (kW)
    P_pv[g,t]     generación PV disponible en hora t (kW)
    P_max[b]      potencia nominal del BESS b (kW)
    E_max[b]      capacidad de almacenamiento del BESS b (kWh)
    η_c[b]        eficiencia de carga del BESS b
    η_d[b]        eficiencia de descarga del BESS b
    SoC0[b]       SoC inicial del BESS b ∈ [0,1]
    SoC_min[b]   SoC mínimo (típ. 0.2)
    SoC_max[b]   SoC máximo (típ. 0.95)
    E_req[v]      energía requerida por VE v en el día (kWh)
    Pev_max[v]   potencia máxima del cargador v (kW)
    W_avail[v,t] {0,1} indica si el VE v está disponible para cargar en t
    P_grid_max    importación máxima permitida desde la red (kW)
    Δt = 1h       paso temporal

Variables de decisión
---------------------
    p_c[b,t]     ≥ 0      potencia de carga del BESS b en t (kW)
    p_d[b,t]     ≥ 0      potencia de descarga del BESS b en t (kW)
    z[b,t]       ∈ {0,1}  1 si BESS está cargando, 0 si descargando
    soc[b,t]     ∈ [0,1]  estado de carga del BESS b al final de t
    p_ev[v,t]    ∈ [0,P]  potencia de carga del VE v en t (kW)
    p_grid[t]    libre    importación neta desde la red en t (+) o exportación (−)

Objetivo
--------
    min Σ_t [ π_buy[t] · p_grid_pos[t] − π_sell[t] · p_grid_neg[t] ]

    donde p_grid[t] = p_grid_pos[t] − p_grid_neg[t]
    (descomposición en partes positiva y negativa para pricing asimétrico)

Restricciones
-------------
1. Balance de potencia (en cada hora):
       Σ_l P_load[l,t] + Σ_v p_ev[v,t] + Σ_b p_c[b,t]
     = Σ_g P_pv[g,t] + Σ_b p_d[b,t] + p_grid[t]

2. Dinámica del SoC del BESS:
       soc[b,t] = soc[b,t-1] + (η_c[b] · p_c[b,t] − p_d[b,t]/η_d[b]) · Δt / E_max[b]
       soc[b,0] = SoC0[b] + ...

3. Límites del SoC:
       SoC_min[b] ≤ soc[b,t] ≤ SoC_max[b]

4. Mutua exclusión carga/descarga (con variable binaria z):
       p_c[b,t] ≤ P_max[b] · z[b,t]
       p_d[b,t] ≤ P_max[b] · (1 − z[b,t])

5. Carga del VE — energía total requerida:
       Σ_t p_ev[v,t] · Δt ≥ E_req[v]    ∀ v ∈ V

6. Carga del VE — disponibilidad:
       p_ev[v,t] ≤ Pev_max[v] · W_avail[v,t]

7. Límite de importación:
       p_grid_pos[t] ≤ P_grid_max

8. Cierre del día (opcional):
       soc[b, T-1] = SoC0[b]    (la batería termina como inicia)


IMPLEMENTACIÓN
==============
Usa PuLP (CBC solver, viene con pip install pulp). Si PuLP no está
disponible, cae a un heurístico greedy basado en time-of-use.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .graph import Asset, AssetType
from .network import Network

# =============================================================================
# Detección de PuLP (opcional)
# =============================================================================
try:
    import pulp
    PULP_AVAILABLE = True
except ImportError:
    PULP_AVAILABLE = False


# =============================================================================
# Configuración del problema
# =============================================================================
@dataclass
class TariffSchedule:
    """
    Tarifa horaria de compra y venta de energía (24h).

    Por defecto: tarifa TOU genérica Ecuador
        - Punta vespertina (18-22): alta
        - Resto del día: baja
    Feed-in tariff (venta) ≈ 60% de la tarifa de compra.
    """
    buy_price: List[float] = field(default_factory=lambda: [
        # 0-5: madrugada (baja)
        0.04, 0.04, 0.04, 0.04, 0.04, 0.04,
        # 6-17: día (media)
        0.08, 0.08, 0.08, 0.08, 0.08, 0.08,
        0.08, 0.08, 0.08, 0.08, 0.08, 0.08,
        # 18-22: punta (alta)
        0.18, 0.18, 0.18, 0.18, 0.18,
        # 23: fin del día (baja)
        0.04,
    ])
    sell_price: List[float] = field(default_factory=lambda: [0.05]*24)


@dataclass
class EVChargingTask:
    """Requerimiento de carga de un VE en el día."""
    asset_id: str               # debe coincidir con Asset.id en Network
    energy_kwh: float           # cuánta energía debe entrarle hoy
    available_hours: List[int]  # horas en que el VE está enchufado
    earliest_hour: int = 0
    latest_hour: int = 23


@dataclass
class OptimizationResult:
    """Resultado del despacho óptimo."""
    status: str
    objective_cost: float                              # $ totales 24h
    bess_charge: Dict[str, List[float]]                # asset_id → 24 valores
    bess_discharge: Dict[str, List[float]]             # asset_id → 24 valores
    bess_soc: Dict[str, List[float]]                   # asset_id → 24 valores [0,1]
    ev_charge: Dict[str, List[float]]                  # asset_id → 24 valores
    grid_import: List[float]                           # 24 valores
    pv_generation: List[float]                         # 24 valores agregados
    load_total: List[float]                            # 24 valores agregados


# =============================================================================
# OPTIMIZADOR PRINCIPAL
# =============================================================================
class DispatchOptimizer:
    """
    Resuelve el problema de despacho óptimo:
        - BESS: cuándo cargar y descargar
        - VE: cuándo cargar (dentro de la ventana disponible)
        - Importación de red: minimizar costo total

    Uso típico:
        opt = DispatchOptimizer(net, tariff)
        opt.add_ev_task(EVChargingTask("EV_010", 22.0, list(range(19,24))))
        result = opt.solve()
    """

    def __init__(
        self,
        network: Network,
        tariff: Optional[TariffSchedule] = None,
        grid_import_limit_kw: float = 1e6,
        soc_min: float = 0.20,
        soc_max: float = 0.95,
    ):
        self.net = network
        self.tariff = tariff or TariffSchedule()
        self.grid_limit = grid_import_limit_kw
        self.soc_min = soc_min
        self.soc_max = soc_max
        self.ev_tasks: Dict[str, EVChargingTask] = {}
        self.dt_hours = 1.0
        self.horizon = 24

    def add_ev_task(self, task: EVChargingTask) -> None:
        if task.asset_id not in self.net.assets:
            raise ValueError(f"VE '{task.asset_id}' no existe en la red.")
        self.ev_tasks[task.asset_id] = task

    # =========================================================================
    # Helpers para extraer datos de la red
    # =========================================================================
    def _bess_assets(self) -> List[Asset]:
        return [a for a in self.net.assets.values()
                if a.is_storage() and a.controllable]

    def _ev_assets(self) -> List[Asset]:
        """VEs controlables que tienen tarea asignada."""
        return [a for a in self.net.assets.values()
                if a.is_ev() and a.controllable and a.id in self.ev_tasks]

    def _pv_assets(self) -> List[Asset]:
        return [a for a in self.net.assets.values() if a.is_pv()]

    def _passive_loads(self) -> List[Asset]:
        """Cargas no controlables (residencial, alumbrado, etc.)."""
        return [a for a in self.net.assets.values()
                if (a.is_load() and not a.controllable) or
                   (a.is_ev() and not a.controllable)]

    def _aggregate_load(self, t: int) -> float:
        return sum(a.power_at_hour(t) for a in self._passive_loads())

    def _aggregate_pv(self, t: int) -> float:
        total = 0.0
        for a in self._pv_assets():
            if a.generation_profile and 0 <= t < len(a.generation_profile):
                total += a.generation_profile[t]
        return total

    # =========================================================================
    # SOLVER PRINCIPAL
    # =========================================================================
    def solve(self) -> OptimizationResult:
        if PULP_AVAILABLE:
            return self._solve_milp()
        return self._solve_heuristic()

    # =========================================================================
    # MILP con PuLP
    # =========================================================================
    def _solve_milp(self) -> OptimizationResult:
        T = list(range(self.horizon))
        bess_list = self._bess_assets()
        ev_list = self._ev_assets()

        prob = pulp.LpProblem("DispatchMILP", pulp.LpMinimize)

        # ── Variables ─────────────────────────────────────────────────
        p_c = {(b.id, t): pulp.LpVariable(
            f"pc_{b.id}_{t}", lowBound=0, upBound=b.rated_kw)
            for b in bess_list for t in T}
        p_d = {(b.id, t): pulp.LpVariable(
            f"pd_{b.id}_{t}", lowBound=0, upBound=b.rated_kw)
            for b in bess_list for t in T}
        z = {(b.id, t): pulp.LpVariable(f"z_{b.id}_{t}", cat="Binary")
             for b in bess_list for t in T}
        soc = {(b.id, t): pulp.LpVariable(
            f"soc_{b.id}_{t}", lowBound=self.soc_min, upBound=self.soc_max)
            for b in bess_list for t in T}

        p_ev = {(v.id, t): pulp.LpVariable(
            f"pev_{v.id}_{t}", lowBound=0, upBound=v.rated_kw)
            for v in ev_list for t in T}

        p_grid_pos = {t: pulp.LpVariable(
            f"gpos_{t}", lowBound=0, upBound=self.grid_limit) for t in T}
        p_grid_neg = {t: pulp.LpVariable(
            f"gneg_{t}", lowBound=0, upBound=self.grid_limit) for t in T}

        # ── Objetivo: minimizar costo neto de energía ────────────────
        prob += pulp.lpSum([
            self.tariff.buy_price[t] * p_grid_pos[t] -
            self.tariff.sell_price[t] * p_grid_neg[t]
            for t in T
        ]), "CostoTotal"

        # ── Restricciones ─────────────────────────────────────────────

        # 1. Balance de potencia en cada hora
        for t in T:
            load_t = self._aggregate_load(t)
            pv_t = self._aggregate_pv(t)
            prob += (
                load_t
                + pulp.lpSum(p_ev[(v.id, t)] for v in ev_list)
                + pulp.lpSum(p_c[(b.id, t)] for b in bess_list)
                ==
                pv_t
                + pulp.lpSum(p_d[(b.id, t)] for b in bess_list)
                + p_grid_pos[t] - p_grid_neg[t]
            ), f"PowerBalance_{t}"

        # 2. Dinámica del SoC del BESS
        for b in bess_list:
            eta_c = b.efficiency_charge or 0.95
            eta_d = b.efficiency_discharge or 0.95
            E_max = b.capacity_kwh
            soc0 = b.soc_initial or 0.5
            for t in T:
                if t == 0:
                    prev = soc0
                    prob += (
                        soc[(b.id, t)] == prev +
                        (eta_c * p_c[(b.id, t)] -
                         p_d[(b.id, t)] / eta_d) * self.dt_hours / E_max
                    ), f"SoCDyn_{b.id}_{t}"
                else:
                    prob += (
                        soc[(b.id, t)] == soc[(b.id, t-1)] +
                        (eta_c * p_c[(b.id, t)] -
                         p_d[(b.id, t)] / eta_d) * self.dt_hours / E_max
                    ), f"SoCDyn_{b.id}_{t}"

        # 3. Mutua exclusión carga/descarga
        for b in bess_list:
            for t in T:
                prob += (p_c[(b.id, t)] <= b.rated_kw * z[(b.id, t)],
                         f"ExcCharge_{b.id}_{t}")
                prob += (p_d[(b.id, t)] <= b.rated_kw * (1 - z[(b.id, t)]),
                         f"ExcDischarge_{b.id}_{t}")

        # 4. Cierre del ciclo: SoC final = SoC inicial
        for b in bess_list:
            prob += (soc[(b.id, 23)] == (b.soc_initial or 0.5),
                     f"CycleClose_{b.id}")

        # 5. Energía requerida por cada VE
        for v in ev_list:
            task = self.ev_tasks[v.id]
            prob += (
                pulp.lpSum(p_ev[(v.id, t)] * self.dt_hours for t in T)
                >= task.energy_kwh
            ), f"EVEnergy_{v.id}"

        # 6. VE solo carga cuando está disponible
        for v in ev_list:
            task = self.ev_tasks[v.id]
            available = set(task.available_hours)
            for t in T:
                if t not in available:
                    prob += (p_ev[(v.id, t)] == 0,
                             f"EVAvail_{v.id}_{t}")

        # ── Resolver ──────────────────────────────────────────────────
        solver = pulp.PULP_CBC_CMD(msg=0)
        prob.solve(solver)

        status = pulp.LpStatus[prob.status]
        objective = pulp.value(prob.objective) or 0.0

        # ── Empaquetar resultados ─────────────────────────────────────
        bess_charge_out = {
            b.id: [pulp.value(p_c[(b.id, t)]) or 0.0 for t in T]
            for b in bess_list
        }
        bess_discharge_out = {
            b.id: [pulp.value(p_d[(b.id, t)]) or 0.0 for t in T]
            for b in bess_list
        }
        bess_soc_out = {
            b.id: [pulp.value(soc[(b.id, t)]) or 0.0 for t in T]
            for b in bess_list
        }
        ev_charge_out = {
            v.id: [pulp.value(p_ev[(v.id, t)]) or 0.0 for t in T]
            for v in ev_list
        }
        grid_import_out = [
            (pulp.value(p_grid_pos[t]) or 0.0) -
            (pulp.value(p_grid_neg[t]) or 0.0)
            for t in T
        ]
        pv_out = [self._aggregate_pv(t) for t in T]
        load_out = [self._aggregate_load(t) for t in T]

        return OptimizationResult(
            status=status,
            objective_cost=objective,
            bess_charge=bess_charge_out,
            bess_discharge=bess_discharge_out,
            bess_soc=bess_soc_out,
            ev_charge=ev_charge_out,
            grid_import=grid_import_out,
            pv_generation=pv_out,
            load_total=load_out,
        )

    # =========================================================================
    # HEURÍSTICO (fallback sin PuLP)
    # =========================================================================
    def _solve_heuristic(self) -> OptimizationResult:
        """
        Heurístico greedy basado en TOU:
          - BESS carga cuando precio es bajo + hay sobrante de PV
          - BESS descarga cuando precio es alto
          - VE carga preferentemente en horas baratas dentro de su ventana
        """
        T = list(range(self.horizon))
        bess_list = self._bess_assets()
        ev_list = self._ev_assets()

        # Inicializar trazas
        p_c_traj = {b.id: [0.0]*24 for b in bess_list}
        p_d_traj = {b.id: [0.0]*24 for b in bess_list}
        soc_traj = {b.id: [(b.soc_initial or 0.5)]*24 for b in bess_list}
        p_ev_traj = {v.id: [0.0]*24 for v in ev_list}

        # Heurístico de BESS: carga en horas baratas, descarga en horas caras
        avg_price = sum(self.tariff.buy_price) / 24
        for b in bess_list:
            E_max = b.capacity_kwh
            P_max = b.rated_kw
            eta_c = b.efficiency_charge or 0.95
            eta_d = b.efficiency_discharge or 0.95
            soc = b.soc_initial or 0.5
            for t in T:
                price = self.tariff.buy_price[t]
                pv_surplus = self._aggregate_pv(t) - self._aggregate_load(t)

                if price < avg_price * 0.7 and soc < self.soc_max:
                    # Carga barata
                    p = min(P_max, (self.soc_max - soc) * E_max / eta_c)
                    p_c_traj[b.id][t] = p
                    soc += eta_c * p / E_max
                elif pv_surplus > 0 and soc < self.soc_max:
                    # Carga con sobrante PV
                    p = min(P_max, pv_surplus, (self.soc_max - soc) * E_max / eta_c)
                    p_c_traj[b.id][t] = p
                    soc += eta_c * p / E_max
                elif price > avg_price * 1.3 and soc > self.soc_min:
                    # Descarga en pico
                    p = min(P_max, (soc - self.soc_min) * E_max * eta_d)
                    p_d_traj[b.id][t] = p
                    soc -= p / (eta_d * E_max)

                soc_traj[b.id][t] = soc

        # Heurístico de VE: carga en horas más baratas dentro de su ventana
        for v in ev_list:
            task = self.ev_tasks[v.id]
            P_max = v.rated_kw
            energy_left = task.energy_kwh
            # Ordenar horas disponibles por precio ascendente
            available_sorted = sorted(
                task.available_hours,
                key=lambda h: self.tariff.buy_price[h]
            )
            for h in available_sorted:
                if energy_left <= 0:
                    break
                p = min(P_max, energy_left)
                p_ev_traj[v.id][h] = p
                energy_left -= p

        # Calcular grid_import resultante
        grid_import = []
        cost = 0.0
        for t in T:
            load_t = self._aggregate_load(t)
            pv_t = self._aggregate_pv(t)
            ev_t = sum(p_ev_traj[v.id][t] for v in ev_list)
            charge_t = sum(p_c_traj[b.id][t] for b in bess_list)
            discharge_t = sum(p_d_traj[b.id][t] for b in bess_list)
            net = load_t + ev_t + charge_t - pv_t - discharge_t
            grid_import.append(net)
            if net > 0:
                cost += net * self.tariff.buy_price[t]
            else:
                cost += net * self.tariff.sell_price[t]

        return OptimizationResult(
            status="Heuristic",
            objective_cost=cost,
            bess_charge=p_c_traj,
            bess_discharge=p_d_traj,
            bess_soc=soc_traj,
            ev_charge=p_ev_traj,
            grid_import=grid_import,
            pv_generation=[self._aggregate_pv(t) for t in T],
            load_total=[self._aggregate_load(t) for t in T],
        )


# =============================================================================
# UTILIDADES DE REPORTE
# =============================================================================

def print_dispatch_summary(result: OptimizationResult) -> None:
    """Imprime un resumen ejecutivo del despacho."""
    print("=" * 64)
    print(f"  DESPACHO ÓPTIMO 24 HORAS — Estado: {result.status}")
    print("=" * 64)
    print(f"  Costo total operación        : ${result.objective_cost:,.2f}")
    print(f"  Energía importada total       : "
          f"{sum(max(g, 0) for g in result.grid_import):,.2f} kWh")
    print(f"  Energía exportada total       : "
          f"{sum(max(-g, 0) for g in result.grid_import):,.2f} kWh")
    print(f"  Generación PV                 : "
          f"{sum(result.pv_generation):,.2f} kWh")
    print(f"  Demanda total                 : "
          f"{sum(result.load_total):,.2f} kWh")
    print()
    print("  ── BESS dispatched ─────────────────────────────────")
    for bess_id in result.bess_charge:
        e_charged = sum(result.bess_charge[bess_id])
        e_discharged = sum(result.bess_discharge[bess_id])
        print(f"    {bess_id}: cargó {e_charged:,.2f} kWh, "
              f"descargó {e_discharged:,.2f} kWh")
    print()
    print("  ── EV charged ──────────────────────────────────────")
    for ev_id, profile in result.ev_charge.items():
        e = sum(profile)
        print(f"    {ev_id}: {e:,.2f} kWh entregados")
    print("=" * 64)


def hourly_table(result: OptimizationResult) -> str:
    """Tabla horaria texto-arte del despacho."""
    lines = ["", "  HORA │ LOAD  PV   GRID  │ BESS_C BESS_D SOC%  │ EV"]
    lines.append("  ─────┼──────────────────┼─────────────────────┼─────")
    for t in range(24):
        load = result.load_total[t]
        pv = result.pv_generation[t]
        grid = result.grid_import[t]
        bess_c = sum(result.bess_charge[b][t] for b in result.bess_charge)
        bess_d = sum(result.bess_discharge[b][t] for b in result.bess_discharge)
        if result.bess_soc:
            soc_avg = sum(result.bess_soc[b][t] for b in result.bess_soc) / len(result.bess_soc)
        else:
            soc_avg = 0
        ev = sum(result.ev_charge[v][t] for v in result.ev_charge)
        lines.append(
            f"  {t:>4} │ {load:>4.1f} {pv:>4.1f} {grid:>+5.1f} "
            f"│ {bess_c:>5.1f}  {bess_d:>5.1f}  {soc_avg*100:>3.0f}%  │ {ev:>4.1f}"
        )
    return "\n".join(lines)
