# -*- coding: utf-8 -*-
"""Endpoints que devuelven GeoJSON para el mapa web."""

from fastapi import APIRouter, HTTPException

from ..storage import StoredNetwork, get_store

router = APIRouter(prefix="/api/v1/networks", tags=["geojson"])


def _get_or_404(network_id: str) -> StoredNetwork:
    stored = get_store().get(network_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return stored


# =============================================================================
# GET /networks/{id}/geojson  — Topología base
# =============================================================================
@router.get("/{network_id}/geojson")
def get_topology_geojson(network_id: str) -> dict:
    """
    Devuelve la red completa como tres FeatureCollections combinables.
    Útil para que el frontend cargue rápidamente la topología sin recalcular.
    """
    stored = _get_or_404(network_id)
    net = stored.network

    # Buses como puntos
    buses_features = []
    for bus in net.buses.values():
        buses_features.append({
            "type": "Feature",
            "properties": {
                "id": bus.id,
                "voltage_kv": bus.voltage_kv,
                "level": bus.level.value,
                "bus_type": bus.bus_type.value,
                "is_mt": bus.is_mt(),
                "zone": bus.zone or "",
            },
            "geometry": {
                "type": "Point",
                "coordinates": list(bus.geometry),
            },
        })

    # Líneas (sin trafos)
    lines_features = []
    for branch in net.branches.values():
        if not branch.is_line():
            continue
        lines_features.append({
            "type": "Feature",
            "properties": {
                "id": branch.id,
                "bus_from": branch.bus_from,
                "bus_to": branch.bus_to,
                "branch_type": branch.branch_type.value,
                "length_m": branch.length_m,
                "rated_a": branch.rated_a or 0.0,
                "conductor_type": branch.conductor_type or "",
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [x, y] for x, y in branch.geometry
                ],
            },
        })

    # Transformadores como puntos
    trafos_features = []
    for trafo in net.transformers():
        x, y = trafo.geometry[0]
        trafos_features.append({
            "type": "Feature",
            "properties": {
                "id": trafo.id,
                "kva": trafo.kva,
                "kv_primary": trafo.kv_primary,
                "kv_secondary": trafo.kv_secondary,
            },
            "geometry": {"type": "Point", "coordinates": [x, y]},
        })

    return {
        "buses": _fc(buses_features, "buses"),
        "lines": _fc(lines_features, "lines"),
        "transformers": _fc(trafos_features, "transformers"),
        "crs": stored.crs,
    }


# =============================================================================
# GET /networks/{id}/results/geojson  — Topología pintada con resultados
# =============================================================================
@router.get("/{network_id}/results/geojson")
def get_results_geojson(network_id: str) -> dict:
    """
    Devuelve GeoJSON enriquecido con resultados del último Solve.
    Si no hay solve, devuelve los atributos sin valores.
    """
    stored = _get_or_404(network_id)
    net = stored.network
    flow = stored.last_solve_result
    bus_v = flow.bus_voltages if flow else {}
    flows = flow.branch_flows if flow else {}

    # Buses con voltage / compliance
    buses_features = []
    for bus in net.buses.values():
        v = bus_v.get(bus.id)
        # Buscar case-insensitive como fallback
        if v is None:
            for k, vv in bus_v.items():
                if k.lower() == bus.id.lower():
                    v = vv
                    break
        props = {
            "id": bus.id,
            "voltage_kv_nom": bus.voltage_kv,
            "is_mt": bus.is_mt(),
        }
        if v is not None:
            props.update({
                "v_pu": round(v.v_pu, 4),
                "v_drop_pct": round(v.v_drop_pct, 3),
                "compliance": v.compliance.value,
            })
        else:
            props.update({
                "v_pu": None, "v_drop_pct": None,
                "compliance": "unknown",
            })
        buses_features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "Point",
                "coordinates": list(bus.geometry),
            },
        })

    # Líneas con loading
    lines_features = []
    for branch in net.branches.values():
        if not branch.is_line():
            continue
        f = flows.get(branch.id)
        if f is None:
            for k, vv in flows.items():
                if k.lower() == branch.id.lower():
                    f = vv
                    break
        props = {
            "id": branch.id,
            "branch_type": branch.branch_type.value,
            "length_m": branch.length_m,
        }
        if f is not None:
            props.update({
                "loading_pct": round(f.loading_pct, 2),
                "current_a": round(f.current_a, 2),
                "p_kw": round(f.p_kw, 2),
                "compliance": f.compliance.value,
            })
        else:
            props["loading_pct"] = 0
            props["compliance"] = "unknown"
        lines_features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "LineString",
                "coordinates": [[x, y] for x, y in branch.geometry],
            },
        })

    # Transformadores con loading
    trafos_features = []
    for trafo in net.transformers():
        f = flows.get(trafo.id)
        if f is None:
            for k, vv in flows.items():
                if k.lower() == trafo.id.lower():
                    f = vv
                    break
        x, y = trafo.geometry[0]
        props = {"id": trafo.id, "kva": trafo.kva}
        if f is not None:
            props.update({
                "loading_pct": round(f.loading_pct, 2),
                "p_kw": round(f.p_kw, 2),
                "compliance": f.compliance.value,
            })
        else:
            props["loading_pct"] = 0
            props["compliance"] = "unknown"
        trafos_features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Point", "coordinates": [x, y]},
        })

    return {
        "buses": _fc(buses_features, "buses_results"),
        "lines": _fc(lines_features, "lines_results"),
        "transformers": _fc(trafos_features, "transformers_results"),
        "crs": stored.crs,
    }


# =============================================================================
# GET /networks/{id}/hosting/geojson  — Capacidad por bus
# =============================================================================
@router.get("/{network_id}/hosting/geojson")
def get_hosting_geojson(network_id: str) -> dict:
    stored = _get_or_404(network_id)
    if stored.last_hosting_results is None:
        raise HTTPException(
            status_code=404,
            detail="No hay resultados de hosting. Ejecute /hosting primero.",
        )
    net = stored.network
    hosting = stored.last_hosting_results

    features = []
    for bus_id, cap in hosting.bus_results.items():
        bus = net.buses.get(bus_id)
        if bus is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "id": cap.bus_id,
                "voltage_nominal_kv": cap.voltage_nominal_kv,
                "pv_hosting_kw": round(cap.pv_hosting_kw, 2),
                "pv_limiting_factor": cap.pv_limiting_factor.value,
                "load_hosting_kw": round(cap.load_hosting_kw, 2),
                "load_limiting_factor": cap.load_limiting_factor.value,
            },
            "geometry": {
                "type": "Point",
                "coordinates": list(bus.geometry),
            },
        })
    return _fc(features, "hosting_capacity")


# =============================================================================
# Helper
# =============================================================================
def _fc(features: list, name: str) -> dict:
    return {
        "type": "FeatureCollection",
        "name": name,
        "features": features,
    }
