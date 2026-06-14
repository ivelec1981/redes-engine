# -*- coding: utf-8 -*-
"""
redes_engine.persistence.results_full
=======================================

Serialización COMPLETA (round-trip) de los objetos de resultados que viven en
`StoredNetwork`:

    - PowerFlowResult       (con BusVoltageResult / BranchFlowResult)
    - ComplianceReport      (con ComplianceFinding)
    - HostingCapacityResults(con BusHostingCapacity)
    - AnnualResults         (con BusAnnualStats / BranchAnnualStats)

A diferencia de `results_io.py` (que produce un *resumen* no recargable), este
módulo reconstruye los objetos VIVOS, de modo que al recargar un `.rsproj` el
workflow, el dashboard y los reportes vuelven a tener `last_solve_result`,
`last_compliance_report`, etc. exactamente como estaban.

Los enums se serializan por su `.name` (estable) y se reconstruyen con `Enum[name]`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# =============================================================================
# Helpers de enums
# =============================================================================
def _enum_name(e: Any) -> Optional[str]:
    return e.name if e is not None else None


# =============================================================================
# PowerFlowResult
# =============================================================================
def power_flow_to_dict(r: Any) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    return {
        "converged": bool(r.converged),
        "iterations": int(r.iterations),
        "total_power_kw": float(r.total_power_kw),
        "total_power_kvar": float(r.total_power_kvar),
        "net_power_kw": float(getattr(r, "net_power_kw", 0.0)),
        "total_losses_kw": float(r.total_losses_kw),
        "total_losses_kvar": float(r.total_losses_kvar),
        "losses_pct": float(r.losses_pct),
        "solver_message": r.solver_message,
        "bus_voltages": {
            bid: {
                "bus_id": v.bus_id,
                "v_magnitude_kv": v.v_magnitude_kv,
                "v_pu": v.v_pu,
                "v_drop_pct": v.v_drop_pct,
                "angle_deg": v.angle_deg,
                "voltage_nominal_kv": v.voltage_nominal_kv,
                "compliance": _enum_name(v.compliance),
                "is_dc": getattr(v, "is_dc", False),
            }
            for bid, v in r.bus_voltages.items()
        },
        "branch_flows": {
            bid: {
                "branch_id": b.branch_id,
                "p_kw": b.p_kw, "q_kvar": b.q_kvar, "s_kva": b.s_kva,
                "current_a": b.current_a, "rated_a": b.rated_a,
                "loading_pct": b.loading_pct,
                "losses_kw": b.losses_kw, "losses_kvar": b.losses_kvar,
                "compliance": _enum_name(b.compliance),
                "is_transformer": getattr(b, "is_transformer", False),
            }
            for bid, b in r.branch_flows.items()
        },
    }


def power_flow_from_dict(d: Optional[Dict[str, Any]]) -> Optional[Any]:
    if not d:
        return None
    from ..core.results import (
        BranchFlowResult,
        BusVoltageResult,
        ComplianceStatus,
        PowerFlowResult,
    )

    def _status(name: Optional[str]) -> ComplianceStatus:
        return ComplianceStatus[name] if name else ComplianceStatus.UNKNOWN

    r = PowerFlowResult(
        converged=d.get("converged", False),
        iterations=d.get("iterations", 0),
        total_power_kw=d.get("total_power_kw", 0.0),
        total_power_kvar=d.get("total_power_kvar", 0.0),
        net_power_kw=d.get("net_power_kw", 0.0),
        total_losses_kw=d.get("total_losses_kw", 0.0),
        total_losses_kvar=d.get("total_losses_kvar", 0.0),
        losses_pct=d.get("losses_pct", 0.0),
        solver_message=d.get("solver_message", ""),
    )
    for bid, v in (d.get("bus_voltages") or {}).items():
        r.bus_voltages[bid] = BusVoltageResult(
            bus_id=v["bus_id"],
            v_magnitude_kv=v["v_magnitude_kv"],
            v_pu=v["v_pu"],
            v_drop_pct=v["v_drop_pct"],
            angle_deg=v["angle_deg"],
            voltage_nominal_kv=v["voltage_nominal_kv"],
            compliance=_status(v.get("compliance")),
            is_dc=v.get("is_dc", False),
        )
    for bid, b in (d.get("branch_flows") or {}).items():
        r.branch_flows[bid] = BranchFlowResult(
            branch_id=b["branch_id"],
            p_kw=b["p_kw"], q_kvar=b["q_kvar"], s_kva=b["s_kva"],
            current_a=b["current_a"], rated_a=b["rated_a"],
            loading_pct=b["loading_pct"],
            losses_kw=b["losses_kw"], losses_kvar=b["losses_kvar"],
            compliance=_status(b.get("compliance")),
            is_transformer=b.get("is_transformer", False),
        )
    return r


# =============================================================================
# ComplianceReport
# =============================================================================
def compliance_to_dict(c: Any) -> Optional[Dict[str, Any]]:
    if c is None:
        return None
    return {
        "framework": _enum_name(c.framework),
        "overall_status": _enum_name(c.overall_status),
        "findings": [
            {
                "severity": _enum_name(f.severity),
                "category": f.category,
                "element_id": f.element_id,
                "actual_value": f.actual_value,
                "limit_value": f.limit_value,
                "units": f.units,
                "message": f.message,
            }
            for f in c.findings
        ],
    }


def compliance_from_dict(d: Optional[Dict[str, Any]]) -> Optional[Any]:
    if not d:
        return None
    from ..core.compliance import (
        ComplianceFinding,
        ComplianceReport,
        NormativeFramework,
    )
    from ..core.results import ComplianceStatus

    def _status(name: Optional[str]) -> ComplianceStatus:
        return ComplianceStatus[name] if name else ComplianceStatus.UNKNOWN

    fw_name = d.get("framework")
    framework = (
        NormativeFramework[fw_name] if fw_name
        else NormativeFramework.ARCERNNR_EC_002_20
    )
    report = ComplianceReport(
        framework=framework,
        overall_status=_status(d.get("overall_status")),
    )
    for f in (d.get("findings") or []):
        report.findings.append(ComplianceFinding(
            severity=_status(f.get("severity")),
            category=f.get("category", ""),
            element_id=f.get("element_id", ""),
            actual_value=f.get("actual_value", 0.0),
            limit_value=f.get("limit_value", 0.0),
            units=f.get("units", ""),
            message=f.get("message", ""),
        ))
    return report


# =============================================================================
# HostingCapacityResults
# =============================================================================
def hosting_to_dict(h: Any) -> Optional[Dict[str, Any]]:
    if h is None:
        return None
    return {
        "network_name": h.network_name,
        "n_buses_analyzed": h.n_buses_analyzed,
        "n_hours_simulated_per_iteration": h.n_hours_simulated_per_iteration,
        "n_iterations_total": h.n_iterations_total,
        "elapsed_seconds": h.elapsed_seconds,
        "method": h.method,
        "bus_results": {
            bid: {
                "bus_id": b.bus_id,
                "voltage_nominal_kv": b.voltage_nominal_kv,
                "pv_hosting_kw": b.pv_hosting_kw,
                "pv_limiting_factor": _enum_name(b.pv_limiting_factor),
                "pv_limiting_hour": b.pv_limiting_hour,
                "pv_limiting_element": b.pv_limiting_element,
                "pv_iterations": b.pv_iterations,
                "load_hosting_kw": b.load_hosting_kw,
                "load_limiting_factor": _enum_name(b.load_limiting_factor),
                "load_limiting_hour": b.load_limiting_hour,
                "load_limiting_element": b.load_limiting_element,
                "load_iterations": b.load_iterations,
            }
            for bid, b in h.bus_results.items()
        },
    }


def hosting_from_dict(d: Optional[Dict[str, Any]]) -> Optional[Any]:
    if not d:
        return None
    from ..hosting.results import (
        BusHostingCapacity,
        HostingCapacityResults,
        LimitingFactor,
    )

    def _lf(name: Optional[str]) -> LimitingFactor:
        return LimitingFactor[name] if name else LimitingFactor.NONE

    h = HostingCapacityResults(
        network_name=d.get("network_name", ""),
        n_buses_analyzed=d.get("n_buses_analyzed", 0),
        n_hours_simulated_per_iteration=d.get("n_hours_simulated_per_iteration", 0),
        n_iterations_total=d.get("n_iterations_total", 0),
        elapsed_seconds=d.get("elapsed_seconds", 0.0),
        method=d.get("method", "bisection"),
    )
    for bid, b in (d.get("bus_results") or {}).items():
        h.bus_results[bid] = BusHostingCapacity(
            bus_id=b["bus_id"],
            voltage_nominal_kv=b["voltage_nominal_kv"],
            pv_hosting_kw=b.get("pv_hosting_kw", 0.0),
            pv_limiting_factor=_lf(b.get("pv_limiting_factor")),
            pv_limiting_hour=b.get("pv_limiting_hour"),
            pv_limiting_element=b.get("pv_limiting_element", ""),
            pv_iterations=b.get("pv_iterations", 0),
            load_hosting_kw=b.get("load_hosting_kw", 0.0),
            load_limiting_factor=_lf(b.get("load_limiting_factor")),
            load_limiting_hour=b.get("load_limiting_hour"),
            load_limiting_element=b.get("load_limiting_element", ""),
            load_iterations=b.get("load_iterations", 0),
        )
    return h


# =============================================================================
# AnnualResults
# =============================================================================
_ANNUAL_SCALAR_FIELDS = (
    "scenario_name", "n_hours_simulated", "n_hours_failed",
    "total_energy_served_mwh", "total_energy_imported_mwh",
    "total_energy_exported_mwh", "total_losses_mwh", "losses_pct",
    "peak_demand_kw", "peak_demand_hour", "avg_demand_kw", "load_factor",
    "peak_losses_kw", "avg_losses_kw",
    "peak_transformer_loading_pct", "peak_transformer_id",
)


def annual_to_dict(a: Any) -> Optional[Dict[str, Any]]:
    if a is None:
        return None
    out: Dict[str, Any] = {f: getattr(a, f) for f in _ANNUAL_SCALAR_FIELDS}
    out["bus_stats"] = {
        bid: {
            "bus_id": s.bus_id,
            "voltage_nominal_kv": s.voltage_nominal_kv,
            "v_pu_min": s.v_pu_min, "v_pu_max": s.v_pu_max,
            "v_drop_max_pct": s.v_drop_max_pct,
            "hours_in_violation": s.hours_in_violation,
            "hours_in_warning": s.hours_in_warning,
            "worst_hour": s.worst_hour,
        }
        for bid, s in a.bus_stats.items()
    }
    out["branch_stats"] = {
        bid: {
            "branch_id": s.branch_id, "rated_a": s.rated_a,
            "loading_max_pct": s.loading_max_pct,
            "loading_avg_pct": s.loading_avg_pct,
            "hours_overloaded": s.hours_overloaded,
            "hours_warning": s.hours_warning,
            "energy_through_kwh": s.energy_through_kwh,
            "energy_losses_kwh": s.energy_losses_kwh,
            "worst_hour": s.worst_hour,
        }
        for bid, s in a.branch_stats.items()
    }
    return out


def annual_from_dict(d: Optional[Dict[str, Any]]) -> Optional[Any]:
    if not d:
        return None
    from ..timeseries.aggregator import (
        AnnualResults,
        BranchAnnualStats,
        BusAnnualStats,
    )
    a = AnnualResults(**{f: d[f] for f in _ANNUAL_SCALAR_FIELDS if f in d})
    for bid, s in (d.get("bus_stats") or {}).items():
        a.bus_stats[bid] = BusAnnualStats(**s)
    for bid, s in (d.get("branch_stats") or {}).items():
        a.branch_stats[bid] = BranchAnnualStats(**s)
    return a


# =============================================================================
# Empaquetado / aplicación completa
# =============================================================================
def results_to_dict(stored: Any) -> Dict[str, Any]:
    """Serializa TODOS los resultados vivos de un StoredNetwork."""
    return {
        "power_flow": power_flow_to_dict(getattr(stored, "last_solve_result", None)),
        "compliance": compliance_to_dict(getattr(stored, "last_compliance_report", None)),
        "hosting": hosting_to_dict(getattr(stored, "last_hosting_results", None)),
        "annual": annual_to_dict(getattr(stored, "last_annual_results", None)),
    }


def apply_results_to_stored(stored: Any, d: Optional[Dict[str, Any]]) -> None:
    """Rehidrata los objetos vivos en un StoredNetwork desde un dict."""
    if not d:
        return
    pf = power_flow_from_dict(d.get("power_flow"))
    if pf is not None:
        stored.last_solve_result = pf
    cr = compliance_from_dict(d.get("compliance"))
    if cr is not None:
        stored.last_compliance_report = cr
    hr = hosting_from_dict(d.get("hosting"))
    if hr is not None:
        stored.last_hosting_results = hr
    ar = annual_from_dict(d.get("annual"))
    if ar is not None:
        stored.last_annual_results = ar
