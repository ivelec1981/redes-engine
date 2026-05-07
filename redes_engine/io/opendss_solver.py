# -*- coding: utf-8 -*-
"""
redes_engine.io.opendss_solver
================================

Bridge bidireccional con OpenDSS — escribe el .dss, ejecuta `Solve` vía
`opendssdirect`, y trae los resultados de vuelta como objetos tipados
(`PowerFlowResult`, `BusVoltageResult`, `BranchFlowResult`).

Flujo típico:
    1. Tener un Network construido (con buses, branches, assets)
    2. Crear OpenDSSSolver(net) — escribe el .dss en disco
    3. solver.solve() — ejecuta Solve en el motor
    4. result = solver.collect_results() — parsea voltajes, flujos, pérdidas
    5. result.evaluate_compliance() — evalúa norma ARCERNNR
    6. print(result.summary())

NOTA: Requiere `pip install opendssdirect.py`.
"""

import os
import tempfile
from typing import Dict, Optional

from ..core.graph import Branch, BranchType
from ..core.network import Network
from ..core.results import (
    BranchFlowResult,
    BusVoltageResult,
    ComplianceStatus,
    PowerFlowResult,
)
from .opendss_bridge import OpenDSSExporter

# =============================================================================
# Detección de opendssdirect
# =============================================================================
try:
    import opendssdirect as dss
    OPENDSS_AVAILABLE = True
except ImportError:
    OPENDSS_AVAILABLE = False


class OpenDSSNotAvailableError(RuntimeError):
    """Se lanza cuando opendssdirect no está instalado."""


# =============================================================================
# SOLVER
# =============================================================================
class OpenDSSSolver:
    """
    Resolvedor de flujo de potencia usando OpenDSS (EPRI).

    Parameters
    ----------
    network : Network
        Red eléctrica a resolver.
    work_dir : str | None
        Directorio temporal donde escribir el .dss. Si es None,
        usa un tempdir del sistema.
    keep_files : bool
        Si True, conserva los archivos .dss generados (útil para debug).
    """

    def __init__(
        self,
        network: Network,
        work_dir: Optional[str] = None,
        keep_files: bool = False,
    ):
        if not OPENDSS_AVAILABLE:
            raise OpenDSSNotAvailableError(
                "opendssdirect no está instalado. "
                "Ejecute: pip install opendssdirect.py"
            )
        self.net = network
        self.work_dir = work_dir or tempfile.mkdtemp(prefix="redes_engine_")
        self.keep_files = keep_files
        self._dss_path: Optional[str] = None
        self._solved = False

    # =========================================================================
    # Ejecución
    # =========================================================================
    def solve(
        self,
        max_iterations: int = 100,
        tolerance: float = 1e-4,
        algorithm: str = "Normal",
    ) -> bool:
        """
        Resuelve el flujo de potencia.

        Parameters
        ----------
        max_iterations : int
            Iteraciones máximas del solver.
        tolerance : float
            Tolerancia de convergencia en pu.
        algorithm : str
            "Normal" o "Newton".

        Returns
        -------
        bool : True si convergió.
        """
        # 1. Escribir el .dss
        self._dss_path = os.path.join(self.work_dir, f"{self.net.name}.dss")
        OpenDSSExporter(self.net).export(self._dss_path)

        # 2. Limpiar el motor
        dss.Text.Command("Clear")

        # 3. Cargar y resolver
        dss.Text.Command(f'Redirect "{self._dss_path}"')
        dss.Text.Command(f"Set MaxIterations={max_iterations}")
        dss.Text.Command(f"Set Tolerance={tolerance}")
        dss.Text.Command(f"Set Algorithm={algorithm}")
        dss.Text.Command("Solve")

        self._solved = dss.Solution.Converged()
        return self._solved

    # =========================================================================
    # Recolección de resultados
    # =========================================================================
    def collect_results(
        self,
        mt_voltage_limit_pct: float = 5.0,
        bt_voltage_limit_pct: float = 8.0,
    ) -> PowerFlowResult:
        """
        Extrae todos los resultados del motor OpenDSS y arma un
        PowerFlowResult con cumplimiento normativo evaluado.
        """
        if not self._solved:
            return PowerFlowResult(
                converged=False,
                solver_message="Solver no ha ejecutado o no convergió.",
            )

        result = PowerFlowResult(
            converged=True,
            iterations=dss.Solution.Iterations(),
            solver_message="OK",
        )

        # ── Potencias y pérdidas totales ──────────────────────────────
        # OpenDSS retorna [P, Q] del circuito (lo que entra desde la fuente)
        total_p_kw, total_q_kvar = dss.Circuit.TotalPower()
        # Signo: OpenDSS retorna negativo cuando entra al sistema; normalizamos
        result.total_power_kw = abs(total_p_kw)
        result.total_power_kvar = abs(total_q_kvar)

        losses = dss.Circuit.Losses()  # [P_W, Q_var]
        result.total_losses_kw = losses[0] / 1000.0
        result.total_losses_kvar = losses[1] / 1000.0
        if result.total_power_kw > 0:
            result.losses_pct = 100.0 * result.total_losses_kw / result.total_power_kw

        # ── Voltajes por bus ──────────────────────────────────────────
        result.bus_voltages = self._collect_bus_voltages(
            mt_voltage_limit_pct, bt_voltage_limit_pct
        )

        # ── Flujos por branch ─────────────────────────────────────────
        result.branch_flows = self._collect_branch_flows()

        return result

    # ─────────────────────────────────────────────────────────────────────
    def _collect_bus_voltages(
        self,
        mt_limit_pct: float,
        bt_limit_pct: float,
    ) -> Dict[str, BusVoltageResult]:
        """Lee voltajes de cada bus y arma BusVoltageResult."""
        bus_results: Dict[str, BusVoltageResult] = {}

        # Iterar buses de OpenDSS
        bus_names = dss.Circuit.AllBusNames()
        for bus_name in bus_names:
            dss.Circuit.SetActiveBus(bus_name)
            # Tensión nominal de este bus (kV LL)
            v_nominal_kv_ll = dss.Bus.kVBase() * (3 ** 0.5)
            # Voltajes por nodo: [Re_n1, Im_n1, Re_n2, ...]
            voltages_complex = dss.Bus.PuVoltage()
            if not voltages_complex:
                continue
            # Magnitud promedio en pu (3 fases)
            mags_pu = []
            angs = []
            for i in range(0, len(voltages_complex), 2):
                if i + 1 < len(voltages_complex):
                    re = voltages_complex[i]
                    im = voltages_complex[i + 1]
                    mag = (re * re + im * im) ** 0.5
                    if mag > 0:
                        mags_pu.append(mag)
                        # Ángulo en grados
                        import math
                        angs.append(math.degrees(math.atan2(im, re)))
            if not mags_pu:
                continue

            v_pu = sum(mags_pu) / len(mags_pu)
            angle_deg = angs[0] if angs else 0.0
            v_mag_kv = v_pu * v_nominal_kv_ll
            v_drop_pct = (1.0 - v_pu) * 100.0

            # Buscar el bus original del Network (por nombre, case-insensitive)
            net_bus = None
            for bid, b in self.net.buses.items():
                if bid.lower() == bus_name.lower():
                    net_bus = b
                    break
            v_nominal_used = (
                net_bus.voltage_kv if net_bus else v_nominal_kv_ll
            )

            voltage_result = BusVoltageResult(
                bus_id=net_bus.id if net_bus else bus_name,
                v_magnitude_kv=v_mag_kv,
                v_pu=v_pu,
                v_drop_pct=v_drop_pct,
                angle_deg=angle_deg,
                voltage_nominal_kv=v_nominal_used,
            )
            voltage_result.evaluate_compliance(mt_limit_pct, bt_limit_pct)
            bus_results[voltage_result.bus_id] = voltage_result

        return bus_results

    # ─────────────────────────────────────────────────────────────────────
    def _collect_branch_flows(self) -> Dict[str, BranchFlowResult]:
        """Lee flujos de cada line + transformer."""
        branch_results: Dict[str, BranchFlowResult] = {}

        # Líneas
        if dss.Lines.First() > 0:
            while True:
                self._read_line_flow(branch_results)
                if dss.Lines.Next() <= 0:
                    break

        # Transformadores
        if dss.Transformers.First() > 0:
            while True:
                self._read_transformer_flow(branch_results)
                if dss.Transformers.Next() <= 0:
                    break

        return branch_results

    def _read_line_flow(self, results: Dict[str, BranchFlowResult]) -> None:
        """Extrae flujo de la línea activa."""
        name = dss.Lines.Name()
        # CktElement activo: la línea
        dss.Circuit.SetActiveElement(f"Line.{name}")
        powers = dss.CktElement.Powers()  # [P1,Q1,P2,Q2,...] kW/kvar
        currents = dss.CktElement.CurrentsMagAng()  # [|I1|, ang1, |I2|, ang2,...]
        losses_w = dss.CktElement.Losses()  # [P_W, Q_var]

        # Tomamos el lado de bus_from (primeros 6 valores son las 3 fases)
        if len(powers) < 2:
            return
        # Sumar las tres fases del extremo 1
        p_kw = sum(powers[i] for i in range(0, min(6, len(powers)), 2))
        q_kvar = sum(powers[i] for i in range(1, min(6, len(powers)), 2))
        s_kva = (p_kw ** 2 + q_kvar ** 2) ** 0.5

        # Corriente promedio (3 fases)
        if currents and len(currents) >= 6:
            i_a = (currents[0] + currents[2] + currents[4]) / 3.0
        elif currents:
            i_a = currents[0]
        else:
            i_a = 0.0

        rated_a = dss.Lines.NormAmps()
        loading_pct = 100.0 * i_a / rated_a if rated_a > 0 else 0.0

        # Buscar el branch original del Network
        net_branch = self.net.branches.get(name)
        if net_branch is None:
            for bid, b in self.net.branches.items():
                if bid.lower() == name.lower():
                    net_branch = b
                    break

        flow = BranchFlowResult(
            branch_id=net_branch.id if net_branch else name,
            p_kw=p_kw,
            q_kvar=q_kvar,
            s_kva=s_kva,
            current_a=i_a,
            rated_a=rated_a if rated_a > 0 else (
                net_branch.rated_a if net_branch else 0.0
            ),
            loading_pct=loading_pct,
            losses_kw=losses_w[0] / 1000.0 if losses_w else 0.0,
            losses_kvar=losses_w[1] / 1000.0 if losses_w and len(losses_w) > 1 else 0.0,
        )
        flow.evaluate_compliance()
        results[flow.branch_id] = flow

    def _read_transformer_flow(self, results: Dict[str, BranchFlowResult]) -> None:
        """Extrae flujo del transformador activo."""
        name = dss.Transformers.Name()
        dss.Circuit.SetActiveElement(f"Transformer.{name}")
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

        # Capacidad nominal (kVA → A en lado primario)
        kva = dss.Transformers.kVA()
        net_branch = self.net.branches.get(name)
        # Fallback case-insensitive (OpenDSS suele lowercasear los nombres)
        if net_branch is None:
            for bid, b in self.net.branches.items():
                if bid.lower() == name.lower():
                    net_branch = b
                    break
        rated_a = 0.0
        if net_branch and net_branch.is_transformer():
            kvp = net_branch.kv_primary or 22.8
            if kvp > 0:
                rated_a = kva / (kvp * (3 ** 0.5))

        loading_pct = (100.0 * s_kva / kva) if kva > 0 else 0.0

        flow = BranchFlowResult(
            branch_id=net_branch.id if net_branch else name,
            p_kw=p_kw,
            q_kvar=q_kvar,
            s_kva=s_kva,
            current_a=i_a,
            rated_a=rated_a,
            loading_pct=loading_pct,
            losses_kw=losses_w[0] / 1000.0 if losses_w else 0.0,
            losses_kvar=losses_w[1] / 1000.0 if losses_w and len(losses_w) > 1 else 0.0,
        )
        flow.evaluate_compliance()
        results[flow.branch_id] = flow

    # =========================================================================
    # Limpieza
    # =========================================================================
    def cleanup(self) -> None:
        """Borra los archivos temporales generados."""
        if self.keep_files:
            return
        if self._dss_path and os.path.exists(self._dss_path):
            try:
                os.remove(self._dss_path)
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
