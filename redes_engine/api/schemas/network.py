# -*- coding: utf-8 -*-
"""
redes_engine.api.schemas.network
=================================

Schemas Pydantic para entrada/salida de la API.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Entrada
# =============================================================================
class CreateNetworkRequest(BaseModel):
    """Body del POST /api/v1/networks."""
    name: str = Field(..., min_length=1, max_length=80)
    layers: Dict[str, Any] = Field(
        ...,
        description=(
            "Diccionario de FeatureCollections GeoJSON. "
            "Llaves esperadas: postes_mt, postes_bt, tramos_mt, tramos_bt, "
            "transformadores, cargas, ev_chargers, solar_pv, bess."
        ),
    )
    snap_tolerance_m: float = 5.0
    crs: str = "EPSG:32717"


class SolveRequest(BaseModel):
    """Body del POST /networks/{id}/solve."""
    mt_voltage_limit_pct: float = 5.0
    bt_voltage_limit_pct: float = 8.0


class HostingRequest(BaseModel):
    include_pv: bool = True
    include_load: bool = True
    n_critical_hours: int = Field(50, ge=1, le=8760)
    tolerance_kw: float = Field(2.0, gt=0)
    max_kw: float = Field(200.0, gt=0)
    forbid_reverse_flow: bool = False


class TimeseriesRequest(BaseModel):
    hours: int = Field(168, ge=1, le=8760)
    scenario_name: str = "Baseline"


class AddAssetRequest(BaseModel):
    """POST /networks/{id}/assets — añadir asset a un bus existente."""
    asset_id: Optional[str] = None       # auto-generado si no se da
    bus_id: str
    asset_type: str = Field(
        ...,
        description="Valor del enum AssetType (ej: 'load_residencial', "
                    "'ev_ac_l2', 'pv_resid', 'bess_btm', 'v2g')",
    )
    rated_kw: float = Field(..., gt=0)
    rated_kvar: float = 0.0
    capacity_kwh: Optional[float] = None
    controllable: bool = False
    bidirectional: bool = False
    # Catálogo opcional: si se especifica un model, sobrescribe los specs
    catalog_model: Optional[str] = None


# =============================================================================
# Salida — Network
# =============================================================================
class BusOut(BaseModel):
    id: str
    voltage_kv: float
    level: str
    bus_type: str
    geometry: List[float]
    zone: Optional[str] = None


class BranchOut(BaseModel):
    id: str
    bus_from: str
    bus_to: str
    branch_type: str
    length_m: float
    rated_a: float = 0.0
    is_transformer: bool = False
    kva: Optional[float] = None


class AssetOut(BaseModel):
    id: str
    bus_id: str
    asset_type: str
    rated_kw: float
    capacity_kwh: Optional[float] = None
    controllable: bool = False


class NetworkSummaryOut(BaseModel):
    id: str
    name: str
    n_buses: int
    n_branches: int
    n_assets: int
    n_buses_mt: int
    n_buses_bt: int
    total_demand_kw: float
    total_generation_kw: float
    total_storage_kwh: float
    is_connected: bool


class NetworkDetailOut(NetworkSummaryOut):
    buses: List[BusOut]
    branches: List[BranchOut]
    assets: List[AssetOut]


# =============================================================================
# Salida — Solve
# =============================================================================
class BusVoltageOut(BaseModel):
    bus_id: str
    v_pu: float
    v_drop_pct: float
    v_kv: float
    compliance: str


class BranchFlowOut(BaseModel):
    branch_id: str
    p_kw: float
    q_kvar: float
    current_a: float
    loading_pct: float
    losses_kw: float
    compliance: str


class SolveResponseOut(BaseModel):
    converged: bool
    iterations: int
    total_power_kw: float
    total_losses_kw: float
    losses_pct: float
    bus_voltages: List[BusVoltageOut]
    branch_flows: List[BranchFlowOut]
    n_violations: int
    n_warnings: int
    solver_message: str


# =============================================================================
# Salida — Hosting Capacity
# =============================================================================
class BusHostingOut(BaseModel):
    bus_id: str
    voltage_nominal_kv: float
    pv_hosting_kw: float
    pv_limiting_factor: str
    pv_limiting_hour: Optional[int]
    load_hosting_kw: float
    load_limiting_factor: str
    load_limiting_hour: Optional[int]


class HostingResponseOut(BaseModel):
    network_name: str
    n_buses_analyzed: int
    n_iterations_total: int
    elapsed_seconds: float
    total_pv_capacity_kw: float
    total_load_capacity_kw: float
    bus_results: List[BusHostingOut]


# =============================================================================
# Salida — Timeseries
# =============================================================================
class TimeseriesResponseOut(BaseModel):
    scenario_name: str
    n_hours_simulated: int
    total_energy_served_mwh: float
    total_losses_mwh: float
    losses_pct: float
    peak_demand_kw: float
    peak_demand_hour: int
    peak_transformer_id: str
    peak_transformer_loading_pct: float
    n_buses_with_violation: int
    n_branches_overloaded: int


# =============================================================================
# Salud / metadatos
# =============================================================================
class HealthOut(BaseModel):
    status: str
    version: str
    opendss_available: bool
    networks_count: int
