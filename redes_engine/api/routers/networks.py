# -*- coding: utf-8 -*-
"""Endpoints CRUD de Networks."""

from fastapi import APIRouter, HTTPException, status

from ...io.gis_importer import GISImporter
from ..schemas.network import (
    AssetOut,
    BranchOut,
    BusOut,
    CreateNetworkRequest,
    NetworkDetailOut,
    NetworkSummaryOut,
)
from ..storage import StoredNetwork, get_store

router = APIRouter(prefix="/api/v1/networks", tags=["networks"])


# =============================================================================
# Helpers — convertir Network a DTOs
# =============================================================================
def _to_summary(stored: StoredNetwork) -> NetworkSummaryOut:
    net = stored.network
    return NetworkSummaryOut(
        id=stored.id,
        name=stored.name,
        n_buses=len(net.buses),
        n_branches=len(net.branches),
        n_assets=len(net.assets),
        n_buses_mt=sum(1 for b in net.buses.values() if b.is_mt()),
        n_buses_bt=sum(1 for b in net.buses.values() if b.is_bt()),
        total_demand_kw=net.total_load_kw(),
        total_generation_kw=net.total_generation_kw(),
        total_storage_kwh=net.total_storage_kwh(),
        is_connected=net.is_connected(),
    )


def _to_detail(stored: StoredNetwork) -> NetworkDetailOut:
    net = stored.network
    base = _to_summary(stored).model_dump()
    base["buses"] = [
        BusOut(
            id=b.id, voltage_kv=b.voltage_kv,
            level=b.level.name, bus_type=b.bus_type.value,
            geometry=[b.geometry[0], b.geometry[1]],
            zone=b.zone,
        ) for b in net.buses.values()
    ]
    base["branches"] = [
        BranchOut(
            id=br.id, bus_from=br.bus_from, bus_to=br.bus_to,
            branch_type=br.branch_type.value,
            length_m=br.length_m, rated_a=br.rated_a or 0.0,
            is_transformer=br.is_transformer(),
            kva=br.kva,
        ) for br in net.branches.values()
    ]
    base["assets"] = [
        AssetOut(
            id=a.id, bus_id=a.bus_id,
            asset_type=a.asset_type.value, rated_kw=a.rated_kw,
            capacity_kwh=a.capacity_kwh,
            controllable=a.controllable,
        ) for a in net.assets.values()
    ]
    return NetworkDetailOut(**base)


# =============================================================================
# POST /api/v1/networks  — Crear
# =============================================================================
@router.post("",
             response_model=NetworkSummaryOut,
             status_code=status.HTTP_201_CREATED)
def create_network(req: CreateNetworkRequest) -> NetworkSummaryOut:
    """
    Construye una Network a partir de un set de capas GeoJSON.

    El body debe contener `layers` con un dict de FeatureCollections,
    p.ej. `{"postes_mt": {...}, "tramos_mt": {...}}`.
    """
    importer = GISImporter(snap_tolerance_m=req.snap_tolerance_m)
    layers_features = {}
    for logical_type, fc in req.layers.items():
        if not isinstance(fc, dict):
            raise HTTPException(
                status_code=400,
                detail=f"Layer '{logical_type}' debe ser un FeatureCollection.",
            )
        features = fc.get("features", []) if fc.get("type") == "FeatureCollection" else fc
        if not isinstance(features, list):
            features = []
        layers_features[logical_type] = features

    try:
        net, report = importer.from_features(
            layers_features, network_name=req.name,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error importing: {e}")

    if report.errors:
        raise HTTPException(
            status_code=400,
            detail=f"Errores en importación: {report.errors}",
        )

    store = get_store()
    stored = store.create(
        name=req.name, network=net,
        crs=req.crs, layers_geojson=req.layers,
    )
    return _to_summary(stored)


# =============================================================================
# GET /api/v1/networks  — Listar
# =============================================================================
@router.get("", response_model=list[NetworkSummaryOut])
def list_networks() -> list[NetworkSummaryOut]:
    store = get_store()
    return [_to_summary(s) for s in store.list_all()]


# =============================================================================
# GET /api/v1/networks/{id}  — Detalle
# =============================================================================
@router.get("/{network_id}", response_model=NetworkDetailOut)
def get_network(network_id: str) -> NetworkDetailOut:
    stored = get_store().get(network_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return _to_detail(stored)


# =============================================================================
# DELETE /api/v1/networks/{id}
# =============================================================================
@router.delete("/{network_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_network(network_id: str) -> None:
    if not get_store().delete(network_id):
        raise HTTPException(status_code=404, detail="Network not found")
