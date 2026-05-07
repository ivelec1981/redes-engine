# -*- coding: utf-8 -*-
"""
redes_engine.timeseries.dispatch
=================================

Estrategias de despacho de BESS y assets controlables durante el análisis 8760h.

Tres estrategias incluidas:
    - StaticDispatch      → usa el perfil_24h del asset tal cual (legacy)
    - PeakShavingDispatch → carga con sobrante PV / descarga en pico de trafo
    - MILPDailyDispatch   → optimiza un MILP por día (requiere PuLP)

Convención:
    Para BESS:  power_kw > 0 = CARGA  (consume energía)
                power_kw < 0 = DESCARGA (inyecta energía)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..core.graph import Asset, AssetType
from ..core.network import Network


# =============================================================================
# Estado interno por BESS durante la simulación
# =============================================================================
@dataclass
class BESSState:
    """Estado SoC dinámico de un BESS durante la simulación 8760h."""
    asset_id: str
    capacity_kwh: float
    rated_kw: float
    soc: float                    # estado de carga actual [0, 1]
    soc_min: float = 0.20
    soc_max: float = 0.95
    eff_charge: float = 0.95
    eff_discharge: float = 0.95
    last_action_kw: float = 0.0   # +charge / -discharge / 0 idle

    def can_charge_kw(self, dt_h: float = 1.0) -> float:
        """kW máximo que puede absorber sin exceder SOC máx."""
        room_kwh = (self.soc_max - self.soc) * self.capacity_kwh
        return min(self.rated_kw, room_kwh / (self.eff_charge * dt_h))

    def can_discharge_kw(self, dt_h: float = 1.0) -> float:
        """kW máximo que puede entregar sin caer debajo de SOC mín."""
        avail_kwh = (self.soc - self.soc_min) * self.capacity_kwh
        return min(self.rated_kw, avail_kwh * self.eff_discharge / dt_h)

    def apply_action(self, power_kw: float, dt_h: float = 1.0) -> None:
        """Actualiza el SOC tras una acción de carga/descarga."""
        self.last_action_kw = power_kw
        if power_kw > 0:   # carga
            energy_in = power_kw * self.eff_charge * dt_h
            self.soc += energy_in / self.capacity_kwh
        elif power_kw < 0:  # descarga
            energy_out = (-power_kw) * dt_h / self.eff_discharge
            self.soc -= energy_out / self.capacity_kwh
        self.soc = max(self.soc_min, min(self.soc_max, self.soc))


# =============================================================================
# Interfaz abstracta
# =============================================================================
class BESSDispatcher(ABC):
    """Estrategia de despacho horario para BESS."""

    @abstractmethod
    def get_bess_power_kw(
        self, hour: int, bess_state: BESSState,
        net_demand_kw: float, pv_generation_kw: float,
        transformer_loading_pct: float,
        **context,
    ) -> float:
        """
        Devuelve potencia BESS en kW para esta hora (signo: + carga, − descarga).

        Parameters
        ----------
        context : dict
            Información adicional opcional. Las estrategias avanzadas
            (e.g. GridSupportDispatch) leen:
                - v_pu : tensión local del bus (pu) — default 1.0
                - freq_hz : frecuencia (Hz) — default 60.0
        """
        ...

    def get_bess_kvar(
        self, hour: int, bess_state: BESSState, **context,
    ) -> float:
        """
        Reactiva del BESS (kvar). + inyecta, − absorbe. Default: 0.

        Las estrategias V/f-Support sobreescriben este método para implementar
        curvas Volt-Var (IEEE 1547 / ARCERNNR Reg. 014/19).
        """
        return 0.0

    def reset(self) -> None:
        """Llamado al inicio de la simulación."""
        pass


# =============================================================================
# Static — comportamiento legacy
# =============================================================================
class StaticDispatch(BESSDispatcher):
    """Sigue el profile_24h_kw del asset literalmente."""

    def get_bess_power_kw(self, hour, bess_state, net_demand_kw,
                           pv_generation_kw, transformer_loading_pct, **context):
        return bess_state.last_action_kw


# =============================================================================
# Peak Shaving — heurístico rápido y efectivo
# =============================================================================
class PeakShavingDispatch(BESSDispatcher):
    """
    Estrategia rule-based:
        1. Si trafo > umbral_alto    → DESCARGAR para reducir carga
        2. Si hay sobrante PV y SOC bajo → CARGAR con sobrante
        3. Si hora valle y SOC < 50% → CARGAR a tarifa baja
        4. Caso contrario           → IDLE
    """

    def __init__(
        self,
        peak_threshold_pct: float = 80.0,
        valley_threshold_pct: float = 30.0,
        low_tariff_hours: Optional[List[int]] = None,
    ):
        self.peak_threshold = peak_threshold_pct
        self.valley_threshold = valley_threshold_pct
        self.low_tariff_hours = low_tariff_hours or [0, 1, 2, 3, 4, 5]

    def get_bess_power_kw(self, hour, bess_state, net_demand_kw,
                           pv_generation_kw, transformer_loading_pct, **context):
        h = hour % 24

        # 1. Trafo sobrecargado → descargar tan rápido como se pueda
        if transformer_loading_pct > self.peak_threshold:
            excess_pct = transformer_loading_pct - self.peak_threshold
            # Descarga proporcional al exceso (más exceso → más descarga)
            target_kw = bess_state.can_discharge_kw() * min(1.0, excess_pct / 20.0)
            return -target_kw

        # 2. Sobrante PV → cargar con el excedente
        pv_surplus = pv_generation_kw - net_demand_kw
        if pv_surplus > 0.5 and bess_state.soc < bess_state.soc_max - 0.05:
            target_kw = min(pv_surplus, bess_state.can_charge_kw())
            return target_kw

        # 3. Hora valle con tarifa baja → cargar barato si SOC < 70%
        if h in self.low_tariff_hours and bess_state.soc < 0.70:
            if transformer_loading_pct < self.valley_threshold:
                target_kw = bess_state.can_charge_kw() * 0.5  # carga moderada
                return target_kw

        return 0.0


# =============================================================================
# GRID_SUPPORT — regulación V/f (IEEE 1547-2018, ARCERNNR Reg. 014/19)
# =============================================================================
class GridSupportDispatch(BESSDispatcher):
    """
    Regulación de tensión y frecuencia (Volt-Watt + Volt-Var + Freq-Watt).

    Cumple IEEE Std 1547-2018 categoría B y la Regulación ARCERNNR 014/19
    sobre apoyo a la red de generación distribuida y BESS.

    Curvas implementadas
    --------------------
    * **Volt-Watt**: limita la potencia activa cuando V está alta.
        - V ≤ V_w_low (1.05 pu)  → P libre (modo peak-shaving secundario)
        - V_w_low < V < V_w_high → P interpola linealmente desde libre a 0
        - V ≥ V_w_high (1.10 pu) → P_carga máxima (absorbe potencia)

    * **Volt-Var**: aporta/absorbe Q según V con deadband simétrica.
        - V_low_var (0.97) < V < V_high_var (1.03) → Q = 0
        - V > V_high_var → Q absorbe linealmente hasta -Q_max en V_max (1.10)
        - V < V_low_var  → Q inyecta linealmente hasta +Q_max en V_min (0.90)

    * **Freq-Watt** (droop primario):
        - Si f > f_high (60.5 Hz) → cargar BESS para absorber sobre-frecuencia
        - Si f < f_low  (59.5 Hz) → descargar BESS para apoyar baja frecuencia
        - Pendiente: 4% (típico Ecuador)

    Prioridades cuando hay conflicto:
        Frecuencia (urgencia sistémica) > Voltaje (local) > Peak-shaving residual.
    """

    def __init__(
        self,
        # Volt-Watt
        v_watt_low: float = 1.05,
        v_watt_high: float = 1.10,
        # Volt-Var (deadband)
        v_var_low: float = 0.97,
        v_var_high: float = 1.03,
        v_min: float = 0.90,
        v_max: float = 1.10,
        q_max_pct_of_p: float = 0.44,    # ratio Q/S (típico cos φ 0.90)
        # Freq-Watt
        f_nominal_hz: float = 60.0,
        f_low_hz: float = 59.5,
        f_high_hz: float = 60.5,
        f_droop_pct: float = 4.0,
        # Peak-shaving residual (cuando V/f normales)
        enable_peak_shaving: bool = True,
        peak_threshold_pct: float = 80.0,
    ):
        # Validaciones de rangos físicos
        if not (v_min < v_var_low < v_var_high < v_max):
            raise ValueError(
                "Curva Volt-Var inválida: requiere "
                "v_min < v_var_low < v_var_high < v_max"
            )
        if not (v_watt_low < v_watt_high <= v_max):
            raise ValueError(
                "Curva Volt-Watt inválida: requiere "
                "v_watt_low < v_watt_high ≤ v_max"
            )
        if not (f_low_hz < f_nominal_hz < f_high_hz):
            raise ValueError(
                "Banda de frecuencia inválida: requiere "
                "f_low_hz < f_nominal_hz < f_high_hz"
            )

        self.v_watt_low = v_watt_low
        self.v_watt_high = v_watt_high
        self.v_var_low = v_var_low
        self.v_var_high = v_var_high
        self.v_min = v_min
        self.v_max = v_max
        self.q_max_pct_of_p = q_max_pct_of_p
        self.f_nominal = f_nominal_hz
        self.f_low = f_low_hz
        self.f_high = f_high_hz
        self.f_droop = f_droop_pct
        self.enable_peak_shaving = enable_peak_shaving
        self.peak_threshold = peak_threshold_pct

    # =========================================================================
    # Helpers de cálculo
    # =========================================================================
    @staticmethod
    def _clamp(x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, x))

    def _volt_watt_factor(self, v_pu: float) -> float:
        """
        Factor multiplicativo a la potencia activa de descarga [0, 1] según V.

        Devuelve 1.0 (sin restricción) cuando V ≤ v_watt_low,
        y 0.0 (potencia bloqueada) cuando V ≥ v_watt_high.
        """
        if v_pu <= self.v_watt_low:
            return 1.0
        if v_pu >= self.v_watt_high:
            return 0.0
        # Interpolación lineal descendente
        slope = 1.0 / (self.v_watt_high - self.v_watt_low)
        return 1.0 - slope * (v_pu - self.v_watt_low)

    def _volt_var_kvar(self, v_pu: float, q_max_kvar: float) -> float:
        """
        Reactiva objetivo (kvar) — positivo inyecta, negativo absorbe.
        Curva Volt-Var con deadband simétrica.
        """
        if self.v_var_low <= v_pu <= self.v_var_high:
            return 0.0
        if v_pu > self.v_var_high:
            # Absorbe Q (signo negativo) para bajar tensión
            frac = (v_pu - self.v_var_high) / max(
                self.v_max - self.v_var_high, 1e-6
            )
            return -q_max_kvar * self._clamp(frac, 0.0, 1.0)
        # v_pu < v_var_low → inyecta Q (signo positivo)
        frac = (self.v_var_low - v_pu) / max(
            self.v_var_low - self.v_min, 1e-6
        )
        return q_max_kvar * self._clamp(frac, 0.0, 1.0)

    def _freq_watt_kw(self, freq_hz: float, p_max_kw: float) -> Optional[float]:
        """
        Potencia activa por frecuencia. Devuelve None si está dentro de banda
        muerta (no hay acción de frecuencia).

        Convención BESS: positivo = carga (absorbe), negativo = descarga.
        """
        if self.f_low <= freq_hz <= self.f_high:
            return None
        # Pendiente droop: 1% de P por (f_droop_pct/100 * f_nominal) Hz
        df_per_pu = (self.f_droop / 100.0) * self.f_nominal
        if freq_hz > self.f_high:
            # Sobre-frecuencia → cargar (absorber generación excedente)
            df = freq_hz - self.f_high
            frac = self._clamp(df / df_per_pu, 0.0, 1.0)
            return p_max_kw * frac
        # Baja frecuencia → descargar
        df = self.f_low - freq_hz
        frac = self._clamp(df / df_per_pu, 0.0, 1.0)
        return -p_max_kw * frac

    # =========================================================================
    # Interfaz BESSDispatcher
    # =========================================================================
    def get_bess_power_kw(self, hour, bess_state, net_demand_kw,
                           pv_generation_kw, transformer_loading_pct, **context):
        v_pu = float(context.get("v_pu", 1.0))
        freq_hz = float(context.get("freq_hz", self.f_nominal))

        # 1. PRIORIDAD 1 — Frecuencia (sistémica)
        freq_target = self._freq_watt_kw(freq_hz, bess_state.rated_kw)
        if freq_target is not None:
            if freq_target > 0:
                return min(freq_target, bess_state.can_charge_kw())
            return -min(-freq_target, bess_state.can_discharge_kw())

        # 2. PRIORIDAD 2 — Volt-Watt (limita descarga si V alta)
        vw_factor = self._volt_watt_factor(v_pu)

        # Si V muy baja: descargar para subir tensión (freq-watt-style)
        if v_pu < self.v_var_low - 0.02:   # 0.95 pu por defecto
            severity = self._clamp(
                (self.v_var_low - 0.02 - v_pu) / 0.05, 0.0, 1.0,
            )
            target = bess_state.can_discharge_kw() * severity
            return -target

        # 3. Acción residual: peak-shaving + V-Watt clipping
        residual = 0.0
        if self.enable_peak_shaving:
            if transformer_loading_pct > self.peak_threshold:
                excess_pct = transformer_loading_pct - self.peak_threshold
                discharge = bess_state.can_discharge_kw() * min(
                    1.0, excess_pct / 20.0,
                )
                residual = -discharge * vw_factor   # V-Watt limita descarga
            else:
                # Cargar con sobrante PV si V no es alta
                pv_surplus = pv_generation_kw - net_demand_kw
                if pv_surplus > 0.5 and v_pu < self.v_watt_high:
                    residual = min(pv_surplus, bess_state.can_charge_kw())

        return residual

    def get_bess_kvar(self, hour, bess_state, **context):
        """
        Q (kvar) de soporte de tensión. Independiente de la potencia activa
        (BESS opera en cuadrante 4Q).
        """
        v_pu = float(context.get("v_pu", 1.0))
        # Q_max disponible: ratio del rated apparent power
        q_max = bess_state.rated_kw * self.q_max_pct_of_p
        return self._volt_var_kvar(v_pu, q_max)


# =============================================================================
# MILP diario (opcional, requiere PuLP)
# =============================================================================
try:
    import pulp
    PULP_AVAILABLE = True
except ImportError:
    PULP_AVAILABLE = False


class MILPDailyDispatch(BESSDispatcher):
    """
    Optimización MILP diaria del despacho BESS.

    Cada día (00:00) optimiza el despacho óptimo para las próximas 24h
    minimizando un objetivo configurable:
        - "cost"      → costo eléctrico bajo tarifa TOU (default)
        - "loading"   → minimizar carga máxima del trafo
        - "losses"    → minimizar pérdidas técnicas
    """

    def __init__(
        self,
        objective: str = "loading",
        tariff_buy_low: float = 0.04,
        tariff_buy_peak: float = 0.20,
        peak_hours: Optional[List[int]] = None,
    ):
        if not PULP_AVAILABLE:
            raise RuntimeError(
                "MILPDailyDispatch requiere PuLP. Instale con: pip install pulp"
            )
        self.objective = objective
        self.tariff_buy_low = tariff_buy_low
        self.tariff_buy_peak = tariff_buy_peak
        self.peak_hours = peak_hours or [18, 19, 20, 21, 22]
        self._daily_plan: Dict[str, List[float]] = {}   # asset_id → 24 valores
        self._current_day = -1

    def _solve_day(
        self, day: int,
        bess_states: Dict[str, BESSState],
        load_forecast_24h: List[float],
        pv_forecast_24h: List[float],
        trafo_kva: float,
    ) -> Dict[str, List[float]]:
        """Resuelve el MILP para un día (24h) y devuelve {bess_id: [kw_h]}."""
        T = list(range(24))
        prob = pulp.LpProblem(f"daily_dispatch_d{day}", pulp.LpMinimize)

        bess_list = list(bess_states.values())

        # Variables: p_charge, p_discharge, soc por BESS y hora
        p_c = {(b.asset_id, t): pulp.LpVariable(
                   f"pc_{b.asset_id}_{t}", lowBound=0, upBound=b.rated_kw)
               for b in bess_list for t in T}
        p_d = {(b.asset_id, t): pulp.LpVariable(
                   f"pd_{b.asset_id}_{t}", lowBound=0, upBound=b.rated_kw)
               for b in bess_list for t in T}
        z = {(b.asset_id, t): pulp.LpVariable(
                f"z_{b.asset_id}_{t}", cat="Binary")
             for b in bess_list for t in T}
        soc = {(b.asset_id, t): pulp.LpVariable(
                   f"soc_{b.asset_id}_{t}",
                   lowBound=b.soc_min, upBound=b.soc_max)
               for b in bess_list for t in T}

        # Variable: pico del trafo
        peak = pulp.LpVariable("peak_load_kw", lowBound=0)

        # Restricciones
        # 1. Mutua exclusión
        for b in bess_list:
            for t in T:
                prob += p_c[(b.asset_id, t)] <= b.rated_kw * z[(b.asset_id, t)]
                prob += p_d[(b.asset_id, t)] <= b.rated_kw * (1 - z[(b.asset_id, t)])

        # 2. SOC dynamics
        for b in bess_list:
            for t in T:
                prev_soc = b.soc if t == 0 else soc[(b.asset_id, t-1)]
                prob += soc[(b.asset_id, t)] == (
                    prev_soc
                    + (b.eff_charge * p_c[(b.asset_id, t)]
                       - p_d[(b.asset_id, t)] / b.eff_discharge)
                       / b.capacity_kwh
                )

        # 3. Carga del trafo por hora ≤ peak
        for t in T:
            net_kw = (
                load_forecast_24h[t] - pv_forecast_24h[t]
                + pulp.lpSum(p_c[(b.asset_id, t)] for b in bess_list)
                - pulp.lpSum(p_d[(b.asset_id, t)] for b in bess_list)
            )
            prob += peak >= net_kw

        # Objetivo según modo
        if self.objective == "loading":
            prob += peak
        elif self.objective == "cost":
            cost = pulp.lpSum(
                self._tariff(t) * (
                    load_forecast_24h[t] - pv_forecast_24h[t]
                    + pulp.lpSum(p_c[(b.asset_id, t)] for b in bess_list)
                    - pulp.lpSum(p_d[(b.asset_id, t)] for b in bess_list)
                )
                for t in T
            )
            prob += cost
        else:  # default: loading
            prob += peak

        prob.solve(pulp.PULP_CBC_CMD(msg=0))

        # Extraer planes
        plans: Dict[str, List[float]] = {}
        for b in bess_list:
            plan = []
            for t in T:
                pc_v = pulp.value(p_c[(b.asset_id, t)]) or 0.0
                pd_v = pulp.value(p_d[(b.asset_id, t)]) or 0.0
                plan.append(pc_v - pd_v)   # signo: + carga, − descarga
            plans[b.asset_id] = plan
        return plans

    def _tariff(self, hour: int) -> float:
        return (self.tariff_buy_peak if hour in self.peak_hours
                else self.tariff_buy_low)

    # =========================================================================
    # Interfaz: planificación lazy día a día
    # =========================================================================
    def precompute_day(
        self, day: int,
        bess_states: Dict[str, BESSState],
        load_forecast_24h: List[float],
        pv_forecast_24h: List[float],
        trafo_kva: float = 75.0,
    ) -> None:
        """Llamar UNA vez al inicio del día con los pronósticos del día."""
        self._daily_plan = self._solve_day(
            day, bess_states, load_forecast_24h, pv_forecast_24h, trafo_kva
        )
        self._current_day = day

    def get_bess_power_kw(self, hour, bess_state, net_demand_kw,
                           pv_generation_kw, transformer_loading_pct, **context):
        h = hour % 24
        plan = self._daily_plan.get(bess_state.asset_id)
        if plan is None or h >= len(plan):
            return 0.0
        target = plan[h]
        # Validar contra estado actual del SoC
        if target > 0:
            return min(target, bess_state.can_charge_kw())
        elif target < 0:
            return -min(-target, bess_state.can_discharge_kw())
        return 0.0


# =============================================================================
# Factory
# =============================================================================
def create_dispatcher(mode: str, **kwargs) -> BESSDispatcher:
    """
    Construye un dispatcher según el modo.

    Modos válidos:
        - "static"       — sigue el perfil del asset literalmente
        - "peak_shaving" — heurístico rule-based (default recomendado)
        - "grid_support" — V/f-droop IEEE 1547 (Volt-Watt + Volt-Var + Freq-Watt)
        - "milp_daily"   — optimización MILP diaria (requiere PuLP)
    """
    mode_lower = mode.lower().strip()
    if mode_lower == "static":
        return StaticDispatch()
    if mode_lower == "peak_shaving":
        return PeakShavingDispatch(**kwargs)
    if mode_lower in ("grid_support", "grid-support", "v_f", "vf"):
        return GridSupportDispatch(**kwargs)
    if mode_lower == "milp_daily":
        return MILPDailyDispatch(**kwargs)
    raise ValueError(
        f"Modo de dispatch desconocido: {mode}. "
        "Use 'static', 'peak_shaving', 'grid_support' o 'milp_daily'."
    )


# =============================================================================
# Helper: construir estados iniciales desde la red
# =============================================================================
def build_bess_states(network: Network) -> Dict[str, BESSState]:
    """Construye {asset_id: BESSState} para todos los BESS de la red."""
    states: Dict[str, BESSState] = {}
    for asset in network.assets.values():
        if not asset.is_storage():
            continue
        if asset.capacity_kwh is None or asset.capacity_kwh <= 0:
            continue
        states[asset.id] = BESSState(
            asset_id=asset.id,
            capacity_kwh=asset.capacity_kwh,
            rated_kw=asset.rated_kw,
            soc=asset.soc_initial or 0.5,
            eff_charge=asset.efficiency_charge or 0.95,
            eff_discharge=asset.efficiency_discharge or 0.95,
        )
    return states
