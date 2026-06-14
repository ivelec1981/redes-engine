# -*- coding: utf-8 -*-
"""
redes_engine.persistence.results_io
====================================

Serialización (sólo lectura/resumen) de los objetos de resultados que viven
en `StoredNetwork` (PowerFlowResult, HostingCapacityResults, AnnualResults,
ComplianceReport). Para el `.rsproj` no necesitamos persistir el detalle
exhaustivo (eso vive en el motor); guardamos un *snapshot* compacto que
permite reconstruir las métricas y el dashboard al recargar.

Cada función devuelve `None` si el resultado no está presente.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# =============================================================================
# PowerFlowResult
# =============================================================================
def power_flow_to_dict(r: Any) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    n_violations = 0
    n_warnings = 0
    n_overload = 0
    worst_v_pu = None
    worst_loading_pct = None
    try:
        n_violations = len(r.buses_in_violation())
        n_warnings = len(r.buses_in_warning())
        n_overload = len(r.branches_overloaded())
        wv = r.worst_voltage()
        if wv is not None:
            worst_v_pu = float(wv.v_pu)
        wb = r.worst_loaded_branch()
        if wb is not None:
            worst_loading_pct = float(wb.loading_pct)
    except (AttributeError, TypeError, ValueError, KeyError):
        # snapshot best-effort: si un resultado parcial no expone un atributo
        # esperado, se omite ese campo en vez de abortar el guardado.
        pass

    return {
        "converged": bool(getattr(r, "converged", False)),
        "iterations": int(getattr(r, "iterations", 0)),
        "total_power_kw": float(getattr(r, "total_power_kw", 0.0)),
        "total_power_kvar": float(getattr(r, "total_power_kvar", 0.0)),
        "total_losses_kw": float(getattr(r, "total_losses_kw", 0.0)),
        "total_losses_kvar": float(getattr(r, "total_losses_kvar", 0.0)),
        "losses_pct": float(getattr(r, "losses_pct", 0.0)),
        "n_buses": len(getattr(r, "bus_voltages", {}) or {}),
        "n_branches": len(getattr(r, "branch_flows", {}) or {}),
        "n_violations": n_violations,
        "n_warnings": n_warnings,
        "n_branches_overloaded": n_overload,
        "worst_v_pu": worst_v_pu,
        "worst_loading_pct": worst_loading_pct,
        "solver_message": getattr(r, "solver_message", ""),
    }


# =============================================================================
# HostingCapacityResults
# =============================================================================
def hosting_results_to_dict(h: Any) -> Optional[Dict[str, Any]]:
    if h is None:
        return None
    bus_results = []
    try:
        for b in (getattr(h, "bus_results", []) or [])[:200]:
            bus_results.append({
                "bus_id": getattr(b, "bus_id", ""),
                "host_capacity_kw": float(getattr(b, "host_capacity_kw", 0.0)),
                "limiting_factor": getattr(b, "limiting_factor", ""),
            })
    except (AttributeError, TypeError, ValueError, KeyError):
        # snapshot best-effort: si un resultado parcial no expone un atributo
        # esperado, se omite ese campo en vez de abortar el guardado.
        pass
    return {
        "n_buses_analyzed": int(getattr(h, "n_buses_analyzed", 0)),
        "total_capacity_kw": float(getattr(h, "total_capacity_kw", 0.0)),
        "bus_results": bus_results,
    }


# =============================================================================
# AnnualResults
# =============================================================================
def annual_results_to_dict(a: Any) -> Optional[Dict[str, Any]]:
    if a is None:
        return None
    return {
        "n_hours_simulated": int(getattr(a, "n_hours_simulated", 0)),
        "total_energy_kwh": float(getattr(a, "total_energy_kwh", 0.0)),
        "total_losses_kwh": float(getattr(a, "total_losses_kwh", 0.0)),
        "peak_kw": float(getattr(a, "peak_kw", 0.0)),
        "peak_hour": int(getattr(a, "peak_hour", 0)),
    }


# =============================================================================
# ComplianceReport
# =============================================================================
def compliance_report_to_dict(c: Any) -> Optional[Dict[str, Any]]:
    if c is None:
        return None
    try:
        viol = c.violations()
        warn = c.warnings()
    except (AttributeError, TypeError, ValueError, KeyError):
        viol, warn = [], []
    overall = getattr(c, "overall_status", None)
    overall_value = getattr(overall, "value", str(overall) if overall else "unknown")
    return {
        "overall_status": overall_value,
        "n_violations": len(viol),
        "n_warnings": len(warn),
    }


# =============================================================================
# Empaquetado completo
# =============================================================================
def stored_results_to_dict(stored: Any) -> Dict[str, Any]:
    """Empaqueta los resultados de un `StoredNetwork` en un dict serializable."""
    return {
        "power_flow": power_flow_to_dict(getattr(stored, "last_solve_result", None)),
        "hosting": hosting_results_to_dict(getattr(stored, "last_hosting_results", None)),
        "annual": annual_results_to_dict(getattr(stored, "last_annual_results", None)),
        "compliance": compliance_report_to_dict(
            getattr(stored, "last_compliance_report", None)
        ),
    }
