# -*- coding: utf-8 -*-
"""
redes_engine.api.routers.assets
==================================

Endpoints para añadir/eliminar assets dinámicamente sobre una red existente.
Habilita edición visual desde el frontend.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from ...catalogs import BESSCatalog, EVChargerCatalog
from ...core.graph import Asset, AssetType
from ..schemas.network import AddAssetRequest, AssetOut
from ..storage import StoredNetwork, get_store

router = APIRouter(prefix="/api/v1/networks", tags=["assets"])


def _get_or_404(network_id: str) -> StoredNetwork:
    stored = get_store().get(network_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return stored


# =============================================================================
# POST /networks/{id}/assets — añadir
# =============================================================================
@router.post("/{network_id}/assets",
             response_model=AssetOut,
             status_code=status.HTTP_201_CREATED)
def add_asset(network_id: str, req: AddAssetRequest) -> AssetOut:
    stored = _get_or_404(network_id)
    net = stored.network

    if req.bus_id not in net.buses:
        raise HTTPException(
            status_code=400,
            detail=f"Bus '{req.bus_id}' no existe en la red.",
        )

    # Resolver AssetType
    try:
        atype_lower = req.asset_type.lower()
        # Buscar por valor (string del enum)
        matched = None
        for at in AssetType:
            if at.value == atype_lower:
                matched = at
                break
        if matched is None:
            raise ValueError
        atype = matched
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"AssetType desconocido: {req.asset_type}",
        )

    asset_id = req.asset_id or f"A_{uuid.uuid4().hex[:6].upper()}"
    if asset_id in net.assets:
        raise HTTPException(
            status_code=409,
            detail=f"Asset '{asset_id}' ya existe.",
        )

    # Si se solicita un modelo de catálogo, usarlo (override)
    if req.catalog_model:
        asset = _resolve_catalog_asset(req.catalog_model, asset_id, req.bus_id)
        if asset is None:
            raise HTTPException(
                status_code=404,
                detail=f"Modelo de catálogo no encontrado: {req.catalog_model}",
            )
    else:
        # Construir manualmente
        cap_kwh = req.capacity_kwh
        # BESS / V2G requieren capacidad
        is_storage_type = atype in (
            AssetType.BESS_BTM, AssetType.BESS_C_AND_I,
            AssetType.BESS_GRID_SCALE, AssetType.PV_BESS_HYBRID,
            AssetType.V2G_BIDIRECTIONAL,
        )
        if is_storage_type and (cap_kwh is None or cap_kwh <= 0):
            cap_kwh = req.rated_kw * 2.0   # default razonable
        asset = Asset(
            id=asset_id, bus_id=req.bus_id,
            asset_type=atype,
            rated_kw=req.rated_kw,
            rated_kvar=req.rated_kvar,
            capacity_kwh=cap_kwh,
            controllable=req.controllable,
            bidirectional=req.bidirectional,
        )

    try:
        net.add_asset(asset)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return AssetOut(
        id=asset.id, bus_id=asset.bus_id,
        asset_type=asset.asset_type.value,
        rated_kw=asset.rated_kw,
        capacity_kwh=asset.capacity_kwh,
        controllable=asset.controllable,
    )


# =============================================================================
# DELETE /networks/{id}/assets/{asset_id} — eliminar
# =============================================================================
@router.delete("/{network_id}/assets/{asset_id}",
                status_code=status.HTTP_204_NO_CONTENT)
def remove_asset(network_id: str, asset_id: str) -> None:
    _get_or_404(network_id)

    # Borrado atómico bajo el lock del store, vía la API pública de Network
    # (que mantiene consistente el índice por bus).
    def _delete(stored) -> bool:
        return stored.network.remove_asset(asset_id)

    removed = get_store().mutate(network_id, _delete)
    if not removed:
        raise HTTPException(status_code=404, detail="Asset not found")


# =============================================================================
# GET /networks/{id}/assets — listar (con filtro opcional por bus)
# =============================================================================
@router.get("/{network_id}/assets")
def list_assets(network_id: str, bus_id: str = "") -> list:
    stored = _get_or_404(network_id)
    net = stored.network
    if bus_id:
        if bus_id not in net.buses:
            raise HTTPException(status_code=404, detail="Bus not found")
        assets = net.assets_at_bus(bus_id)
    else:
        assets = list(net.assets.values())
    return [
        AssetOut(
            id=a.id, bus_id=a.bus_id,
            asset_type=a.asset_type.value,
            rated_kw=a.rated_kw,
            capacity_kwh=a.capacity_kwh,
            controllable=a.controllable,
        ).model_dump()
        for a in assets
    ]


# =============================================================================
# GET /catalogs/ev_chargers, /catalogs/bess
# =============================================================================
catalogs_router = APIRouter(prefix="/api/v1/catalogs", tags=["catalogs"])


@catalogs_router.get("/ev_chargers")
def list_ev_chargers() -> list:
    """Lista todos los productos del catálogo de cargadores VE."""
    cat = EVChargerCatalog.load_default()
    return [
        {
            "model": p.model,
            "manufacturer": p.manufacturer,
            "category": p.category,
            "rated_kw": p.rated_kw,
            "v2g_capable": p.v2g_capable,
            "cost_usd_approx": p.cost_usd_approx,
            "notes": p.notes,
        }
        for p in cat
    ]


@catalogs_router.get("/bess")
def list_bess() -> list:
    """Lista todos los productos del catálogo de BESS."""
    cat = BESSCatalog.load_default()
    return [
        {
            "model": p.model,
            "manufacturer": p.manufacturer,
            "category": p.category,
            "rated_kw": p.rated_kw,
            "capacity_kwh": p.capacity_kwh,
            "duration_hours": round(p.duration_hours, 2),
            "round_trip_efficiency": p.round_trip_efficiency,
            "cost_usd_approx": p.cost_usd_approx,
            "notes": p.notes,
        }
        for p in cat
    ]


# =============================================================================
# Helper interno
# =============================================================================
def _resolve_catalog_asset(model: str, asset_id: str, bus_id: str):
    """Resuelve un modelo del catálogo a Asset."""
    ev = EVChargerCatalog.load_default().find_by_model(model)
    if ev is not None:
        return ev.to_asset(asset_id, bus_id)
    bess = BESSCatalog.load_default().find_by_model(model)
    if bess is not None:
        return bess.to_asset(asset_id, bus_id)
    return None
