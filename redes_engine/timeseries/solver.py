# -*- coding: utf-8 -*-
"""
redes_engine.timeseries.solver
================================

Resuelve flujo de potencia hora-a-hora durante 8760 horas.

Estrategia eficiente:
    1. Construir el .dss UNA SOLA VEZ con valores nominales
    2. Para cada hora h:
        - Modificar kW de cada Load/Generator vía  Edit <name> kw=<value>
        - Llamar Solve
        - Recolectar métricas mínimas (sin reconstruir todo)
    3. Acumular vía AnnualAggregator

Mapeo asset_type → perfil
-------------------------
El método _profile_for_asset_type() asigna automáticamente un perfil de la
ProfileLibrary a cada asset según su tipo. Es configurable para casos
específicos (zonas Sierra/Costa/Oriente).
"""

from typing import Callable, Dict, List, Optional

from ..core.graph import Asset, AssetType
from ..core.network import Network
from ..core.results import (
    BranchFlowResult,
    BusVoltageResult,
    ComplianceStatus,
    PowerFlowResult,
)
from .aggregator import AnnualAggregator, AnnualResults
from .dispatch import (
    BESSDispatcher,
    BESSState,
    MILPDailyDispatch,
    PeakShavingDispatch,
    StaticDispatch,
    build_bess_states,
    create_dispatcher,
)
from .profiles import HOURS_PER_DAY, HOURS_PER_YEAR, ProfileLibrary

# =============================================================================
# Detección de opendssdirect
# =============================================================================
try:
    import opendssdirect as dss
    OPENDSS_AVAILABLE = True
except ImportError:
    OPENDSS_AVAILABLE = False


# =============================================================================
# Mapeo asset_type → perfil
# =============================================================================
DEFAULT_PROFILE_MAP: Dict[AssetType, str] = {
    AssetType.LOAD_RESIDENCIAL:    "residential_sierra",
    AssetType.LOAD_COMERCIAL:      "commercial",
    AssetType.LOAD_INDUSTRIAL:     "industrial_24h",
    AssetType.ALUMBRADO_PUBLICO:   "street_lighting",
    AssetType.EV_CHARGER_AC_L1:    "ev_residential",
    AssetType.EV_CHARGER_AC_L2:    "ev_residential",
    AssetType.EV_CHARGER_DC_FAST:  "ev_dc_fast",
    AssetType.EV_CHARGER_DC_ULTRA: "ev_dc_fast",
    AssetType.EV_FLEET_DEPOT:      "ev_dc_fast",
    AssetType.SOLAR_PV_RESID:      "pv_sierra",
    AssetType.SOLAR_PV_COMERCIAL:  "pv_sierra",
    AssetType.SOLAR_PV_UTILITY:    "pv_sierra",
}


# =============================================================================
# TIME SERIES SOLVER
# =============================================================================
class TimeSeriesSolver:
    """
    Resuelve la red en serie temporal (típicamente 8760 horas).

    Uso típico:
        profiles = ProfileLibrary.ecuador_default()
        solver = TimeSeriesSolver(network, profiles)
        annual = solver.run(hours=8760)
        print(annual.summary())

    Para depurar con horizonte corto:
        annual = solver.run(hours=168)   # 1 semana
    """

    def __init__(
        self,
        network: Network,
        profiles: Optional[Dict[str, List[float]]] = None,
        profile_map: Optional[Dict[AssetType, str]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        dispatch_mode: str = "static",
        dispatch_kwargs: Optional[Dict] = None,
    ):
        """
        Parameters
        ----------
        dispatch_mode : str
            "static"       → BESS sigue su perfil_24h_kw literalmente (legacy)
            "peak_shaving" → heurística rule-based (default recomendado)
            "milp_daily"   → optimización MILP diaria (requiere PuLP)
        dispatch_kwargs : dict | None
            Parámetros específicos del dispatcher.
        """
        if not OPENDSS_AVAILABLE:
            raise RuntimeError(
                "opendssdirect no disponible. "
                "Instale: pip install opendssdirect.py"
            )
        self.net = network
        self.profiles = profiles or ProfileLibrary.ecuador_default()
        self.profile_map = profile_map or DEFAULT_PROFILE_MAP
        self.progress_callback = progress_callback

        self.dispatch_mode = dispatch_mode
        self.dispatcher: BESSDispatcher = create_dispatcher(
            dispatch_mode, **(dispatch_kwargs or {})
        )
        self._bess_states: Dict[str, BESSState] = {}

        self._dss_loaded = False
        self._known_loads: List[str] = []
        self._known_gens: List[str] = []
        self._agg_load_kw = 0.0
        self._agg_pv_kw = 0.0

    # =========================================================================
    # Selección de perfil para un asset
    # =========================================================================
    def _profile_for_asset(self, asset: Asset) -> Optional[List[float]]:
        # 1. Si el asset trae perfil 24h, lo expandimos a 8760 horas
        if asset.profile_24h_kw and len(asset.profile_24h_kw) == 24:
            # Repetimos 365 veces, normalizado por rated_kw
            rated = max(asset.rated_kw, 1e-6)
            return [
                asset.profile_24h_kw[h % 24] / rated
                for h in range(HOURS_PER_YEAR)
            ]
        # 2. Buscar en ProfileLibrary según asset_type
        profile_name = self.profile_map.get(asset.asset_type)
        if profile_name and profile_name in self.profiles:
            return self.profiles[profile_name]
        # 3. Sin perfil → asume operación constante
        return None

    # =========================================================================
    # Construcción del .dss base
    # =========================================================================
    def _build_dss(self) -> None:
        """Construye el .dss una sola vez con valores nominales."""
        import os
        import tempfile

        from ..io.opendss_bridge import OpenDSSExporter
        tmpdir = tempfile.mkdtemp(prefix="ts_solver_")
        path = os.path.join(tmpdir, f"{self.net.name}.dss")
        OpenDSSExporter(self.net).export(path)

        dss.Text.Command("Clear")
        dss.Text.Command(f'Redirect "{path}"')

        # Capturar nombres de loads y generators ya creados (lowercase)
        if dss.Loads.First() > 0:
            while True:
                self._known_loads.append(dss.Loads.Name())
                if dss.Loads.Next() <= 0:
                    break
        if dss.Generators.First() > 0:
            while True:
                self._known_gens.append(dss.Generators.Name())
                if dss.Generators.Next() <= 0:
                    break

        # Inicializar estados BESS y crear "Load ghost" controlados por el dispatcher.
        # Los Storage originales se mantienen pero con kw=0 (inertes); el dispatcher
        # opera vía un Load adicional cuyo kW puede ser positivo (carga) o
        # negativo (descarga = inyección).
        self._bess_states = build_bess_states(self.net)
        self._bess_disp_load_names: List[str] = []
        for bess_id, state in self._bess_states.items():
            asset = self.net.assets.get(bess_id)
            if asset is None:
                continue
            bus = self.net.buses.get(asset.bus_id)
            if bus is None:
                continue
            disp_name = f"{bess_id}_disp"
            dss.Text.Command(
                f"New Load.{disp_name} bus1={asset.bus_id} phases=3 "
                f"kv={bus.voltage_kv:.4f} kw=0 kvar=0 model=1"
            )
            # Deshabilitar el Storage original para que no compita
            dss.Text.Command(f"Disable Storage.{bess_id}")
            self._bess_disp_load_names.append(disp_name.lower())

        self._dss_loaded = True

    # =========================================================================
    # Actualización de loads/generators por hora
    # =========================================================================
    def _update_for_hour(self, hour: int) -> None:
        """Modifica kW de cada load/gen según los perfiles en la hora h."""
        # Pre-calcular agregados de la hora (para el dispatcher)
        agg_load_kw = 0.0
        agg_pv_kw = 0.0

        for asset_id, asset in self.net.assets.items():
            profile = self._profile_for_asset(asset)
            if profile is None:
                continue
            multiplier = profile[hour] if hour < len(profile) else 0.0
            new_kw = asset.rated_kw * multiplier

            asset_lower = asset_id.lower()
            if asset.is_load() or asset.is_ev():
                # No actualizar BESS (lo decide el dispatcher)
                if asset.is_storage():
                    continue
                if asset_lower in self._known_loads:
                    dss.Text.Command(
                        f"Edit Load.{asset_id} kw={new_kw:.4f}"
                    )
                    agg_load_kw += new_kw
            elif asset.is_pv() or asset.is_generator():
                if asset_lower in self._known_gens:
                    dss.Text.Command(
                        f"Edit Generator.{asset_id} kw={new_kw:.4f}"
                    )
                    agg_pv_kw += new_kw

        # Guardar agregados de la hora para el despacho (que se hace en run()
        # para poder ordenar el paso predictor-corrector cuando aplica).
        self._agg_load_kw = agg_load_kw
        self._agg_pv_kw = agg_pv_kw

    def _dispatch_bess_for_hour(
        self, hour: int, agg_load_kw: float, agg_pv_kw: float,
        v_pu_map: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Decide la potencia (y reactiva) de cada BESS en la hora actual y la
        aplica al .dss vía el Load ghost (kw>0 carga, kw<0 descarga/inyección).

        El SoC se actualiza EXACTAMENTE una vez por hora (aquí). Para modos
        con realimentación de tensión (`needs_voltage_feedback`), el solver
        llama a este método una sola vez con `v_pu_map` ya poblado tras el
        flujo predictor.

        Parameters
        ----------
        v_pu_map : dict {asset_id: v_pu} | None
            Tensión real del bus de cada BESS (post-flujo predictor). Si None,
            el dispatcher recibe el default nominal (1.0) vía su contexto.
        """
        # Si no hay BESS, salir rápido
        if not self._bess_states:
            return

        # Estimar carga del trafo HEURÍSTICAMENTE (sin re-resolver)
        # Asumimos 1 trafo principal — para el dispatcher solo necesitamos un proxy
        net_demand = agg_load_kw - agg_pv_kw
        # cargabilidad estimada: net_demand / kva_total_trafos
        total_kva = sum(
            (br.kva or 0.0) for br in self.net.branches.values()
            if br.is_transformer()
        )
        trafo_loading_pct = (
            100.0 * net_demand / total_kva if total_kva > 0 else 0.0
        )

        # Para MILP daily, recalcular el plan al inicio de cada día
        if isinstance(self.dispatcher, MILPDailyDispatch):
            day = hour // HOURS_PER_DAY
            if day != self.dispatcher._current_day:
                # Construir forecast 24h de carga y PV
                day_start = day * HOURS_PER_DAY
                day_end = min(day_start + 24, HOURS_PER_YEAR)
                load_24h = []
                pv_24h = []
                for t in range(day_start, day_start + 24):
                    if t >= HOURS_PER_YEAR:
                        load_24h.append(0); pv_24h.append(0)
                        continue
                    l = 0.0; p = 0.0
                    for asset in self.net.assets.values():
                        prof = self._profile_for_asset(asset)
                        if prof is None: continue
                        m = prof[t] if t < len(prof) else 0.0
                        v = asset.rated_kw * m
                        if asset.is_storage():
                            continue
                        if asset.is_load() or asset.is_ev():
                            l += v
                        elif asset.is_pv() or asset.is_generator():
                            p += v
                    load_24h.append(l)
                    pv_24h.append(p)
                self.dispatcher.precompute_day(
                    day, self._bess_states,
                    load_24h, pv_24h, trafo_kva=total_kva or 75.0,
                )

        nominal_freq = getattr(self.dispatcher, "f_nominal", 60.0)

        # Para cada BESS, consultar al dispatcher y aplicar
        for asset_id, state in self._bess_states.items():
            v_pu = (v_pu_map or {}).get(asset_id, 1.0)
            power_kw = self.dispatcher.get_bess_power_kw(
                hour=hour, bess_state=state,
                net_demand_kw=net_demand,
                pv_generation_kw=agg_pv_kw,
                transformer_loading_pct=trafo_loading_pct,
                v_pu=v_pu, freq_hz=nominal_freq,
            )
            kvar = self.dispatcher.get_bess_kvar(
                hour=hour, bess_state=state, v_pu=v_pu, freq_hz=nominal_freq,
            )
            # Límite de cuadrante (4Q): la potencia aparente S=√(P²+Q²) del
            # inversor no puede exceder su rating. Si P+Q lo superan, se recorta
            # la reactiva (la activa tiene prioridad).
            rated = state.rated_kw
            if rated > 0:
                max_q = max(rated * rated - power_kw * power_kw, 0.0) ** 0.5
                kvar = max(-max_q, min(max_q, kvar))
            # Actualizar SoC (lógica interna) — una sola vez por hora
            state.apply_action(power_kw, dt_h=1.0)

            # Aplicar al .dss vía el ghost Load asociado a este BESS.
            # Convención Load OpenDSS: kw>0 consume, kw<0 inyecta;
            # kvar>0 absorbe reactiva. El dispatcher entrega Q>0 = INYECTAR,
            # por eso se escribe con signo invertido.
            disp_name = f"{asset_id}_disp"
            dss.Text.Command(
                f"Edit Load.{disp_name} kw={power_kw:.4f} kvar={-kvar:.4f}"
            )

    def _read_bus_vpu(self, bus_id: str) -> float:
        """Lee la tensión (pu) promedio de fases de un bus tras el flujo."""
        target = bus_id.lower()
        for bus_name in dss.Circuit.AllBusNames():
            if bus_name.lower() != target:
                continue
            dss.Circuit.SetActiveBus(bus_name)
            voltages = dss.Bus.PuVoltage()
            mags = []
            for i in range(0, len(voltages), 2):
                if i + 1 < len(voltages):
                    re_, im_ = voltages[i], voltages[i + 1]
                    mag = (re_ * re_ + im_ * im_) ** 0.5
                    if mag > 0:
                        mags.append(mag)
            return sum(mags) / len(mags) if mags else 1.0
        return 1.0

    def _zero_bess_ghosts(self) -> None:
        """Pone los Load ghost de los BESS a 0 (para el flujo predictor)."""
        for asset_id in self._bess_states:
            dss.Text.Command(f"Edit Load.{asset_id}_disp kw=0 kvar=0")

    # =========================================================================
    # Recolección rápida de resultados (versión ligera para 8760 iteraciones)
    # =========================================================================
    def _collect_hourly(self) -> PowerFlowResult:
        """
        Versión más ligera de la recolección, sin construir todos los
        objetos detallados — solo lo necesario para el aggregator.
        """
        result = PowerFlowResult(converged=True,
                                  iterations=dss.Solution.Iterations())
        # Potencias globales.
        # OpenDSS TotalPower() devuelve la potencia en la fuente con convención
        # negativa cuando el circuito CONSUME (la fuente entrega). Por eso
        # net_import = -total_p es positivo al importar y negativo al exportar.
        total_p, total_q = dss.Circuit.TotalPower()
        result.total_power_kw = abs(total_p)
        result.total_power_kvar = abs(total_q)
        result.net_power_kw = -total_p
        losses = dss.Circuit.Losses()
        result.total_losses_kw = losses[0] / 1000.0
        result.total_losses_kvar = losses[1] / 1000.0
        if result.total_power_kw > 0:
            result.losses_pct = 100.0 * result.total_losses_kw / result.total_power_kw

        # Voltajes por bus
        for bus_name in dss.Circuit.AllBusNames():
            dss.Circuit.SetActiveBus(bus_name)
            v_nominal_ll = dss.Bus.kVBase() * (3 ** 0.5)
            voltages = dss.Bus.PuVoltage()
            mags = []
            for i in range(0, len(voltages), 2):
                if i + 1 < len(voltages):
                    re, im = voltages[i], voltages[i + 1]
                    mag = (re * re + im * im) ** 0.5
                    if mag > 0:
                        mags.append(mag)
            if not mags:
                continue
            v_pu = sum(mags) / len(mags)
            v_drop_pct = (1.0 - v_pu) * 100.0

            # Buscar bus original
            bus_id = bus_name
            for bid, b in self.net.buses.items():
                if bid.lower() == bus_name.lower():
                    bus_id = bid
                    break

            net_bus = self.net.buses.get(bus_id)
            v_nom = net_bus.voltage_kv if net_bus else v_nominal_ll
            is_dc = net_bus.is_dc() if net_bus else False
            mt_limit = 5.0
            bt_limit = 8.0
            limit = mt_limit if v_nom >= 1.0 else bt_limit

            v_res = BusVoltageResult(
                bus_id=bus_id,
                v_magnitude_kv=v_pu * v_nominal_ll,
                v_pu=v_pu,
                v_drop_pct=v_drop_pct,
                angle_deg=0.0,
                voltage_nominal_kv=v_nom,
                is_dc=is_dc,
            )
            mag = abs(v_drop_pct)
            if is_dc:
                # Bus DC: los límites AC no aplican → no evaluado.
                v_res.compliance = ComplianceStatus.UNKNOWN
            elif mag > limit:
                v_res.compliance = ComplianceStatus.VIOLATION
            elif mag > 0.8 * limit:
                v_res.compliance = ComplianceStatus.WARNING
            else:
                v_res.compliance = ComplianceStatus.OK
            result.bus_voltages[bus_id] = v_res

        # Flujos por línea y trafo (solo lo crítico)
        if dss.Lines.First() > 0:
            while True:
                self._read_branch_flow(result, "Line")
                if dss.Lines.Next() <= 0:
                    break
        if dss.Transformers.First() > 0:
            while True:
                self._read_branch_flow(result, "Transformer")
                if dss.Transformers.Next() <= 0:
                    break

        return result

    def _read_branch_flow(self, result: PowerFlowResult, kind: str) -> None:
        if kind == "Line":
            name = dss.Lines.Name()
            rated_a = dss.Lines.NormAmps()
        else:
            name = dss.Transformers.Name()
            rated_a = 0.0
        dss.Circuit.SetActiveElement(f"{kind}.{name}")
        powers = dss.CktElement.Powers()
        currents = dss.CktElement.CurrentsMagAng()
        losses_w = dss.CktElement.Losses()

        if len(powers) < 2:
            return
        p_kw = sum(powers[i] for i in range(0, min(6, len(powers)), 2))
        q_kvar = sum(powers[i] for i in range(1, min(6, len(powers)), 2))
        s_kva = (p_kw ** 2 + q_kvar ** 2) ** 0.5

        if currents and len(currents) >= 6:
            i_a = (currents[0] + currents[2] + currents[4]) / 3.0
        elif currents:
            i_a = currents[0]
        else:
            i_a = 0.0

        # Para trafos, la cargabilidad se calcula sobre kVA
        if kind == "Transformer":
            kva = dss.Transformers.kVA()
            loading = (100.0 * s_kva / kva) if kva > 0 else 0.0
        else:
            loading = (100.0 * i_a / rated_a) if rated_a > 0 else 0.0

        # Buscar branch original (case-insensitive)
        branch_id = name
        for bid, br in self.net.branches.items():
            if bid.lower() == name.lower():
                branch_id = bid
                break

        flow = BranchFlowResult(
            branch_id=branch_id, p_kw=p_kw, q_kvar=q_kvar, s_kva=s_kva,
            current_a=i_a, rated_a=rated_a,
            loading_pct=loading,
            losses_kw=losses_w[0] / 1000.0 if losses_w else 0.0,
            losses_kvar=(losses_w[1] / 1000.0
                         if losses_w and len(losses_w) > 1 else 0.0),
            is_transformer=(kind == "Transformer"),
        )
        if loading > 100.0:
            flow.compliance = ComplianceStatus.VIOLATION
        elif loading > 80.0:
            flow.compliance = ComplianceStatus.WARNING
        else:
            flow.compliance = ComplianceStatus.OK
        result.branch_flows[branch_id] = flow

    # =========================================================================
    # ENTRADA PRINCIPAL
    # =========================================================================
    def run(
        self,
        hours: int = HOURS_PER_YEAR,
        scenario_name: str = "Baseline",
    ) -> AnnualResults:
        """
        Ejecuta la simulación temporal.

        Parameters
        ----------
        hours : int
            Número de horas a simular (default 8760 = 1 año).
        scenario_name : str

        Returns
        -------
        AnnualResults
        """
        if hours < 1 or hours > HOURS_PER_YEAR:
            raise ValueError(f"hours debe estar en [1, {HOURS_PER_YEAR}]")

        if not self._dss_loaded:
            self._build_dss()

        aggregator = AnnualAggregator()
        needs_vf = (
            self.dispatcher.needs_voltage_feedback() and bool(self._bess_states)
        )

        for hour in range(hours):
            try:
                self._update_for_hour(hour)

                if needs_vf:
                    # Paso PREDICTOR: resolver con BESS en reposo para leer la
                    # tensión "sin compensar" en cada bus de BESS.
                    self._zero_bess_ghosts()
                    dss.Solution.Solve()
                    if not dss.Solution.Converged():
                        continue
                    v_pu_map = {
                        aid: self._read_bus_vpu(
                            self.net.assets[aid].bus_id
                        )
                        for aid in self._bess_states
                        if aid in self.net.assets
                    }
                    # Paso CORRECTOR: despachar con la tensión real y re-resolver.
                    self._dispatch_bess_for_hour(
                        hour, self._agg_load_kw, self._agg_pv_kw, v_pu_map,
                    )
                    dss.Solution.Solve()
                else:
                    self._dispatch_bess_for_hour(
                        hour, self._agg_load_kw, self._agg_pv_kw,
                    )
                    dss.Solution.Solve()

                if not dss.Solution.Converged():
                    continue
                hourly_result = self._collect_hourly()
                aggregator.update(hour, hourly_result)
            except Exception:
                continue

            if self.progress_callback and (hour % 100 == 0 or hour == hours - 1):
                self.progress_callback(hour + 1, hours)

        return aggregator.finalize(scenario_name=scenario_name)
