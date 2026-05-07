# -*- coding: utf-8 -*-
"""Endpoints de análisis: solve, hosting, timeseries."""

from fastapi import APIRouter, HTTPException

from ...core.compliance import ARCERNNR_EC, ComplianceAnalyzer
from ...core.results import ComplianceStatus
from ..schemas.network import (
    BranchFlowOut,
    BusHostingOut,
    BusVoltageOut,
    HostingRequest,
    HostingResponseOut,
    SolveRequest,
    SolveResponseOut,
    TimeseriesRequest,
    TimeseriesResponseOut,
)
from ..storage import StoredNetwork, get_store

router = APIRouter(prefix="/api/v1/networks", tags=["analysis"])


def _get_or_404(network_id: str) -> StoredNetwork:
    stored = get_store().get(network_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return stored


# =============================================================================
# POST /networks/{id}/solve   — Flujo de potencia
# =============================================================================
@router.post("/{network_id}/solve", response_model=SolveResponseOut)
def solve_powerflow(network_id: str, req: SolveRequest = SolveRequest()):
    stored = _get_or_404(network_id)

    try:
        from ...io.opendss_solver import (
            OpenDSSNotAvailableError,
            OpenDSSSolver,
        )
        with OpenDSSSolver(stored.network) as solver:
            converged = solver.solve()
            if not converged:
                raise HTTPException(
                    status_code=500,
                    detail="OpenDSS no convergió",
                )
            result = solver.collect_results(
                mt_voltage_limit_pct=req.mt_voltage_limit_pct,
                bt_voltage_limit_pct=req.bt_voltage_limit_pct,
            )
        # Compliance ARCERNNR
        compliance = ComplianceAnalyzer(ARCERNNR_EC).analyze(result)
        # Cachear
        stored.last_solve_result = result
        stored.last_compliance_report = compliance
    except OpenDSSNotAvailableError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Solver error: {e}")

    n_violations = len(compliance.violations()) if compliance else 0
    n_warnings = len(compliance.warnings()) if compliance else 0

    return SolveResponseOut(
        converged=result.converged,
        iterations=result.iterations,
        total_power_kw=result.total_power_kw,
        total_losses_kw=result.total_losses_kw,
        losses_pct=result.losses_pct,
        bus_voltages=[
            BusVoltageOut(
                bus_id=v.bus_id,
                v_pu=round(v.v_pu, 4),
                v_drop_pct=round(v.v_drop_pct, 3),
                v_kv=round(v.v_magnitude_kv, 4),
                compliance=v.compliance.value,
            ) for v in result.bus_voltages.values()
        ],
        branch_flows=[
            BranchFlowOut(
                branch_id=b.branch_id,
                p_kw=round(b.p_kw, 2),
                q_kvar=round(b.q_kvar, 2),
                current_a=round(b.current_a, 2),
                loading_pct=round(b.loading_pct, 2),
                losses_kw=round(b.losses_kw, 4),
                compliance=b.compliance.value,
            ) for b in result.branch_flows.values()
        ],
        n_violations=n_violations,
        n_warnings=n_warnings,
        solver_message=result.solver_message,
    )


# =============================================================================
# POST /networks/{id}/hosting — Host Capacity
# =============================================================================
@router.post("/{network_id}/hosting", response_model=HostingResponseOut)
def run_hosting_capacity(network_id: str, req: HostingRequest = HostingRequest()):
    stored = _get_or_404(network_id)

    try:
        from ...hosting import HostingCapacityAnalyzer
        analyzer = HostingCapacityAnalyzer(
            stored.network,
            forbid_reverse_flow=req.forbid_reverse_flow,
        )
        results = analyzer.analyze_all(
            include_pv=req.include_pv,
            include_load=req.include_load,
            n_critical_hours=req.n_critical_hours,
            tolerance_kw=req.tolerance_kw,
            max_kw=req.max_kw,
        )
        stored.last_hosting_results = results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hosting error: {e}")

    return HostingResponseOut(
        network_name=results.network_name,
        n_buses_analyzed=results.n_buses_analyzed,
        n_iterations_total=results.n_iterations_total,
        elapsed_seconds=round(results.elapsed_seconds, 3),
        total_pv_capacity_kw=round(results.total_pv_capacity_kw(), 2),
        total_load_capacity_kw=round(results.total_load_capacity_kw(), 2),
        bus_results=[
            BusHostingOut(
                bus_id=b.bus_id,
                voltage_nominal_kv=b.voltage_nominal_kv,
                pv_hosting_kw=round(b.pv_hosting_kw, 2),
                pv_limiting_factor=b.pv_limiting_factor.value,
                pv_limiting_hour=b.pv_limiting_hour,
                load_hosting_kw=round(b.load_hosting_kw, 2),
                load_limiting_factor=b.load_limiting_factor.value,
                load_limiting_hour=b.load_limiting_hour,
            ) for b in results.bus_results.values()
        ],
    )


# =============================================================================
# POST /networks/{id}/timeseries  — 8760h
# =============================================================================
@router.post("/{network_id}/timeseries", response_model=TimeseriesResponseOut)
def run_timeseries(network_id: str, req: TimeseriesRequest = TimeseriesRequest()):
    stored = _get_or_404(network_id)

    try:
        from ...timeseries import ProfileLibrary, TimeSeriesSolver
        profiles = ProfileLibrary.ecuador_default()
        solver = TimeSeriesSolver(network=stored.network, profiles=profiles)
        annual = solver.run(hours=req.hours, scenario_name=req.scenario_name)
        stored.last_annual_results = annual
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Timeseries error: {e}")

    return TimeseriesResponseOut(
        scenario_name=annual.scenario_name,
        n_hours_simulated=annual.n_hours_simulated,
        total_energy_served_mwh=round(annual.total_energy_served_mwh, 2),
        total_losses_mwh=round(annual.total_losses_mwh, 3),
        losses_pct=round(annual.losses_pct, 3),
        peak_demand_kw=round(annual.peak_demand_kw, 2),
        peak_demand_hour=annual.peak_demand_hour,
        peak_transformer_id=annual.peak_transformer_id,
        peak_transformer_loading_pct=round(annual.peak_transformer_loading_pct, 2),
        n_buses_with_violation=len(annual.buses_with_violation_hours),
        n_branches_overloaded=len(annual.branches_with_overload_hours),
    )
