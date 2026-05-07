# -*- coding: utf-8 -*-
"""
redes_engine.hosting.hosting_capacity
======================================

Analizador de Host Capacity con bisección + horas críticas.

Algoritmo principal:
    Para cada bus:
        1. Inyectar candidato test_kw (PV o carga adicional)
        2. Para cada hora crítica:
             - Solve OpenDSS
             - Si V/I/trafo violan → registrar y abandonar
        3. Bisección entre [lo, hi] hasta tolerancia
        4. Reportar capacidad máxima + factor limitante
"""

import time
from typing import Dict, List, Optional, Tuple

from ..core.graph import Asset, AssetType, Bus
from ..core.network import Network
from ..core.results import ComplianceStatus
from ..io.opendss_bridge import OpenDSSExporter
from ..timeseries.profiles import HOURS_PER_YEAR, ProfileLibrary
from .results import (
    BusHostingCapacity,
    HostingCapacityResults,
    LimitingFactor,
)

try:
    import opendssdirect as dss
    OPENDSS_AVAILABLE = True
except ImportError:
    OPENDSS_AVAILABLE = False


# =============================================================================
# Límites normativos default
# =============================================================================
DEFAULT_VMIN_PU = 0.92          # Caída máxima 8% (BT)
DEFAULT_VMAX_PU = 1.05          # Subida máxima 5% (regulación PV)
DEFAULT_LINE_LOADING_MAX = 100.0
DEFAULT_TRAFO_LOADING_MAX = 100.0


# =============================================================================
# ANALIZADOR PRINCIPAL
# =============================================================================
class HostingCapacityAnalyzer:
    """
    Calcula la capacidad de alojamiento (PV y carga) de cada bus de la red.

    Uso típico:
        analyzer = HostingCapacityAnalyzer(network, profiles)
        results = analyzer.analyze_all(
            include_pv=True, include_load=True,
            n_critical_hours=80,
            tolerance_kw=2.0, max_kw=500,
        )
        print(results.summary())
        print(results.ranking_table())
    """

    def __init__(
        self,
        network: Network,
        profiles: Optional[Dict[str, List[float]]] = None,
        vmin_pu: float = DEFAULT_VMIN_PU,
        vmax_pu: float = DEFAULT_VMAX_PU,
        line_loading_max: float = DEFAULT_LINE_LOADING_MAX,
        trafo_loading_max: float = DEFAULT_TRAFO_LOADING_MAX,
        forbid_reverse_flow: bool = False,
    ):
        """
        Parameters
        ----------
        forbid_reverse_flow : bool
            Si True, se considera violación cuando el trafo opera en flujo
            inverso (PV inyecta más de lo que consume el lado BT).
            Por defecto False — la regulación moderna PERMITE flujo inverso
            siempre que se respeten límites térmicos y de voltaje.
        """
        if not OPENDSS_AVAILABLE:
            raise RuntimeError(
                "opendssdirect no disponible. "
                "Instale: pip install opendssdirect.py"
            )
        self.net = network
        self.profiles = profiles or ProfileLibrary.ecuador_default()
        self.vmin_pu = vmin_pu
        self.vmax_pu = vmax_pu
        self.line_loading_max = line_loading_max
        self.trafo_loading_max = trafo_loading_max
        self.forbid_reverse_flow = forbid_reverse_flow

        self._dss_loaded = False
        self._known_loads: List[str] = []
        self._known_gens: List[str] = []
        self._iterations = 0

    # =========================================================================
    # ENTRADA PRINCIPAL
    # =========================================================================
    def analyze_all(
        self,
        include_pv: bool = True,
        include_load: bool = True,
        n_critical_hours: int = 80,
        tolerance_kw: float = 2.0,
        max_kw: float = 500.0,
        bus_filter: Optional[List[str]] = None,
    ) -> HostingCapacityResults:
        """
        Analiza Host Capacity para todos los buses.

        Parameters
        ----------
        include_pv : bool
            Calcular capacidad PV (generación distribuida).
        include_load : bool
            Calcular capacidad de carga (VE adicional).
        n_critical_hours : int
            Cantidad de horas críticas a evaluar por iteración.
        tolerance_kw : float
            Precisión de la bisección.
        max_kw : float
            Cota superior del rango de búsqueda.
        bus_filter : list[str] | None
            Si se especifica, solo se analizan estos buses.

        Returns
        -------
        HostingCapacityResults
        """
        t_start = time.time()
        self._iterations = 0

        if not self._dss_loaded:
            self._build_base_dss()

        # Identificar horas críticas
        critical_hours_pv = self._critical_hours_for_pv(n_critical_hours)
        critical_hours_load = self._critical_hours_for_load(n_critical_hours)

        target_buses = (
            [self.net.buses[b] for b in bus_filter
             if b in self.net.buses]
            if bus_filter else list(self.net.buses.values())
        )

        results = HostingCapacityResults(
            network_name=self.net.name,
            n_buses_analyzed=len(target_buses),
            n_hours_simulated_per_iteration=n_critical_hours,
            method=f"bisection (tol={tolerance_kw} kW, max={max_kw} kW)",
        )

        for bus in target_buses:
            cap = BusHostingCapacity(
                bus_id=bus.id,
                voltage_nominal_kv=bus.voltage_kv,
            )

            if include_pv:
                self._analyze_pv_for_bus(
                    bus, cap, critical_hours_pv, tolerance_kw, max_kw
                )
            if include_load:
                self._analyze_load_for_bus(
                    bus, cap, critical_hours_load, tolerance_kw, max_kw
                )

            results.bus_results[bus.id] = cap

        results.elapsed_seconds = time.time() - t_start
        results.n_iterations_total = self._iterations
        return results

    # =========================================================================
    # CONSTRUCCIÓN DEL .DSS BASE
    # =========================================================================
    def _build_base_dss(self) -> None:
        """Construye el .dss una sola vez con la red base."""
        import os
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="hosting_")
        path = os.path.join(tmpdir, f"{self.net.name}.dss")
        OpenDSSExporter(self.net).export(path)

        dss.Text.Command("Clear")
        dss.Text.Command(f'Redirect "{path}"')

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

        self._dss_loaded = True

    # =========================================================================
    # HORAS CRÍTICAS
    # =========================================================================
    def _critical_hours_for_pv(self, n: int) -> List[int]:
        """
        Horas críticas para análisis PV: alta generación PV + baja carga.
        El "peor caso" para PV es cuando hay sobre-voltaje (mucha PV inyectando
        sin carga local que la consuma).
        """
        pv_profile = self.profiles.get("pv_sierra", [0] * HOURS_PER_YEAR)
        load_profile = self.profiles.get("residential_sierra", [0] * HOURS_PER_YEAR)

        # Score = generación − consumo
        scores = [
            pv_profile[h] - load_profile[h] * 0.5
            for h in range(HOURS_PER_YEAR)
        ]
        # Top n hours con mayor score
        ranked = sorted(range(HOURS_PER_YEAR), key=lambda i: -scores[i])
        return sorted(ranked[:n])

    def _critical_hours_for_load(self, n: int) -> List[int]:
        """
        Horas críticas para análisis de carga: máxima demanda residencial,
        sin generación PV (típicamente noche).
        """
        load_profile = self.profiles.get("residential_sierra", [0] * HOURS_PER_YEAR)
        pv_profile = self.profiles.get("pv_sierra", [0] * HOURS_PER_YEAR)

        scores = [
            load_profile[h] - pv_profile[h] * 0.5
            for h in range(HOURS_PER_YEAR)
        ]
        ranked = sorted(range(HOURS_PER_YEAR), key=lambda i: -scores[i])
        return sorted(ranked[:n])

    # =========================================================================
    # ANÁLISIS PV PARA UN BUS
    # =========================================================================
    def _analyze_pv_for_bus(
        self, bus: Bus, cap: BusHostingCapacity,
        critical_hours: List[int], tol_kw: float, max_kw: float,
    ) -> None:
        ghost_name = f"GHOST_PV_{bus.id}"
        # Crear ghost generator en este bus
        dss.Text.Command(
            f"New Generator.{ghost_name} bus1={bus.id} phases=3 "
            f"kv={bus.voltage_kv:.4f} kw=0 pf=1.0 model=1"
        )
        try:
            # Test si max passes
            violation = self._first_violation_pv(
                ghost_name, max_kw, critical_hours, "pv_sierra",
            )
            cap.pv_iterations += 1
            self._iterations += 1

            if violation is None:
                # No hay límite alcanzable en [0, max_kw]
                cap.pv_hosting_kw = max_kw
                cap.pv_limiting_factor = LimitingFactor.NONE
                return

            # Bisección
            lo, hi = 0.0, max_kw
            last_violation = violation
            while hi - lo > tol_kw:
                mid = (lo + hi) / 2.0
                v = self._first_violation_pv(
                    ghost_name, mid, critical_hours, "pv_sierra",
                )
                cap.pv_iterations += 1
                self._iterations += 1
                if v is None:
                    lo = mid
                else:
                    hi = mid
                    last_violation = v

            cap.pv_hosting_kw = lo
            cap.pv_limiting_factor = last_violation[0]
            cap.pv_limiting_hour = last_violation[1]
            cap.pv_limiting_element = last_violation[2]
        finally:
            # Limpiar el ghost
            dss.Text.Command(f"Edit Generator.{ghost_name} kw=0")
            dss.Text.Command(f"Disable Generator.{ghost_name}")

    def _first_violation_pv(
        self, ghost_name: str, kw: float,
        hours: List[int], pv_profile_name: str,
    ) -> Optional[Tuple[LimitingFactor, int, str]]:
        """
        Inyecta `kw` en el ghost generator y barre las horas críticas.
        Devuelve la primera violación encontrada o None si todo pasa.
        """
        # 1. Setear loads/gens base para cada hora
        pv_profile = self.profiles.get(pv_profile_name, [1.0] * HOURS_PER_YEAR)

        for h in hours:
            self._update_base_for_hour(h)
            # 2. Setear kW del ghost: kw × multiplicador del perfil PV en h
            mult = pv_profile[h] if h < len(pv_profile) else 0.0
            ghost_kw = kw * mult
            dss.Text.Command(f"Edit Generator.{ghost_name} kw={ghost_kw:.4f}")
            dss.Solution.Solve()
            if not dss.Solution.Converged():
                return (LimitingFactor.CONVERGENCE_FAIL, h, "")

            # 3. Chequear violaciones (overvoltage, thermal, reverse trafo)
            v = self._check_violations_pv(h)
            if v is not None:
                return v
        return None

    # =========================================================================
    # ANÁLISIS DE CARGA PARA UN BUS
    # =========================================================================
    def _analyze_load_for_bus(
        self, bus: Bus, cap: BusHostingCapacity,
        critical_hours: List[int], tol_kw: float, max_kw: float,
    ) -> None:
        ghost_name = f"GHOST_LD_{bus.id}"
        dss.Text.Command(
            f"New Load.{ghost_name} bus1={bus.id} phases=3 "
            f"kv={bus.voltage_kv:.4f} kw=0 kvar=0 model=1"
        )
        try:
            violation = self._first_violation_load(
                ghost_name, max_kw, critical_hours, "ev_residential",
            )
            cap.load_iterations += 1
            self._iterations += 1
            if violation is None:
                cap.load_hosting_kw = max_kw
                cap.load_limiting_factor = LimitingFactor.NONE
                return

            lo, hi = 0.0, max_kw
            last_violation = violation
            while hi - lo > tol_kw:
                mid = (lo + hi) / 2.0
                v = self._first_violation_load(
                    ghost_name, mid, critical_hours, "ev_residential",
                )
                cap.load_iterations += 1
                self._iterations += 1
                if v is None:
                    lo = mid
                else:
                    hi = mid
                    last_violation = v

            cap.load_hosting_kw = lo
            cap.load_limiting_factor = last_violation[0]
            cap.load_limiting_hour = last_violation[1]
            cap.load_limiting_element = last_violation[2]
        finally:
            dss.Text.Command(f"Edit Load.{ghost_name} kw=0")
            dss.Text.Command(f"Disable Load.{ghost_name}")

    def _first_violation_load(
        self, ghost_name: str, kw: float,
        hours: List[int], load_profile_name: str,
    ) -> Optional[Tuple[LimitingFactor, int, str]]:
        load_profile = self.profiles.get(load_profile_name, [1.0] * HOURS_PER_YEAR)
        for h in hours:
            self._update_base_for_hour(h)
            mult = load_profile[h] if h < len(load_profile) else 0.0
            ghost_kw = kw * mult
            dss.Text.Command(f"Edit Load.{ghost_name} kw={ghost_kw:.4f}")
            dss.Solution.Solve()
            if not dss.Solution.Converged():
                return (LimitingFactor.CONVERGENCE_FAIL, h, "")
            v = self._check_violations_load(h)
            if v is not None:
                return v
        return None

    # =========================================================================
    # ACTUALIZACIÓN DE LOADS BASE PARA UNA HORA
    # =========================================================================
    def _update_base_for_hour(self, hour: int) -> None:
        """Actualiza loads/gens base de la red según los perfiles."""
        from ..timeseries.solver import DEFAULT_PROFILE_MAP

        for asset_id, asset in self.net.assets.items():
            asset_lower = asset_id.lower()
            profile_name = DEFAULT_PROFILE_MAP.get(asset.asset_type)
            profile = (
                self.profiles.get(profile_name) if profile_name else None
            )
            if profile is None:
                continue
            mult = profile[hour] if hour < len(profile) else 0.0
            new_kw = asset.rated_kw * mult

            if asset.is_load() or asset.is_ev():
                if asset_lower in self._known_loads:
                    dss.Text.Command(
                        f"Edit Load.{asset_id} kw={new_kw:.4f}"
                    )
            elif asset.is_pv() or asset.is_generator():
                if asset_lower in self._known_gens:
                    dss.Text.Command(
                        f"Edit Generator.{asset_id} kw={new_kw:.4f}"
                    )

    # =========================================================================
    # CHEQUEO DE VIOLACIONES
    # =========================================================================
    def _check_violations_pv(
        self, hour: int,
    ) -> Optional[Tuple[LimitingFactor, int, str]]:
        """
        Para análisis PV, verificar:
            - Sobre-voltaje (V > vmax_pu)  ← más común
            - Sobrecarga térmica de líneas (corriente inversa)
            - Sobrecarga del trafo (S > S_nom)
            - Flujo inverso por trafo (potencia regresa al alimentador)
        """
        # 1. Voltajes
        for bus_name in dss.Circuit.AllBusNames():
            dss.Circuit.SetActiveBus(bus_name)
            voltages = dss.Bus.PuVoltage()
            if not voltages:
                continue
            mags = [
                (voltages[i] ** 2 + voltages[i + 1] ** 2) ** 0.5
                for i in range(0, len(voltages), 2)
                if i + 1 < len(voltages)
            ]
            if not mags:
                continue
            v_pu = sum(mags) / len(mags)
            if v_pu > self.vmax_pu:
                return (LimitingFactor.OVERVOLTAGE, hour, bus_name)

        # 2. Líneas - sobrecarga
        if dss.Lines.First() > 0:
            while True:
                name = dss.Lines.Name()
                rated_a = dss.Lines.NormAmps()
                dss.Circuit.SetActiveElement(f"Line.{name}")
                currents = dss.CktElement.CurrentsMagAng()
                if currents and len(currents) >= 2 and rated_a > 0:
                    i_a = currents[0]
                    if (100.0 * i_a / rated_a) > self.line_loading_max:
                        return (LimitingFactor.THERMAL_LINE, hour, name)
                if dss.Lines.Next() <= 0:
                    break

        # 3. Trafos
        if dss.Transformers.First() > 0:
            while True:
                name = dss.Transformers.Name()
                kva = dss.Transformers.kVA()
                dss.Circuit.SetActiveElement(f"Transformer.{name}")
                powers = dss.CktElement.Powers()
                if powers and kva > 0:
                    p_kw = sum(
                        powers[i] for i in range(0, min(6, len(powers)), 2)
                    )
                    q_kvar = sum(
                        powers[i] for i in range(1, min(6, len(powers)), 2)
                    )
                    s_kva = (p_kw ** 2 + q_kvar ** 2) ** 0.5
                    if (100.0 * s_kva / kva) > self.trafo_loading_max:
                        return (LimitingFactor.THERMAL_TRANSFORMER, hour, name)
                    # Flujo inverso: opcional según regulación
                    # Algunas regulaciones lo prohíben; la moderna lo permite
                    # si los límites térmicos y de voltaje se respetan.
                    if self.forbid_reverse_flow and p_kw < -0.10 * kva:
                        return (LimitingFactor.REVERSE_FLOW_TRAFO, hour, name)
                if dss.Transformers.Next() <= 0:
                    break
        return None

    def _check_violations_load(
        self, hour: int,
    ) -> Optional[Tuple[LimitingFactor, int, str]]:
        """
        Para análisis de carga, verificar:
            - Sub-voltaje (V < vmin_pu)  ← más común
            - Sobrecarga térmica de líneas
            - Sobrecarga del trafo
        """
        # 1. Voltajes
        for bus_name in dss.Circuit.AllBusNames():
            dss.Circuit.SetActiveBus(bus_name)
            voltages = dss.Bus.PuVoltage()
            if not voltages:
                continue
            mags = [
                (voltages[i] ** 2 + voltages[i + 1] ** 2) ** 0.5
                for i in range(0, len(voltages), 2)
                if i + 1 < len(voltages)
            ]
            if not mags:
                continue
            v_pu = sum(mags) / len(mags)
            if v_pu < self.vmin_pu:
                return (LimitingFactor.UNDERVOLTAGE, hour, bus_name)

        # 2. Líneas
        if dss.Lines.First() > 0:
            while True:
                name = dss.Lines.Name()
                rated_a = dss.Lines.NormAmps()
                dss.Circuit.SetActiveElement(f"Line.{name}")
                currents = dss.CktElement.CurrentsMagAng()
                if currents and len(currents) >= 2 and rated_a > 0:
                    i_a = currents[0]
                    if (100.0 * i_a / rated_a) > self.line_loading_max:
                        return (LimitingFactor.THERMAL_LINE, hour, name)
                if dss.Lines.Next() <= 0:
                    break

        # 3. Trafos
        if dss.Transformers.First() > 0:
            while True:
                name = dss.Transformers.Name()
                kva = dss.Transformers.kVA()
                dss.Circuit.SetActiveElement(f"Transformer.{name}")
                powers = dss.CktElement.Powers()
                if powers and kva > 0:
                    p_kw = sum(
                        powers[i] for i in range(0, min(6, len(powers)), 2)
                    )
                    q_kvar = sum(
                        powers[i] for i in range(1, min(6, len(powers)), 2)
                    )
                    s_kva = (p_kw ** 2 + q_kvar ** 2) ** 0.5
                    if (100.0 * s_kva / kva) > self.trafo_loading_max:
                        return (LimitingFactor.THERMAL_TRANSFORMER, hour, name)
                if dss.Transformers.Next() <= 0:
                    break
        return None
