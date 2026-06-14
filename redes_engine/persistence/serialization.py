# -*- coding: utf-8 -*-
"""
redes_engine.persistence.serialization
========================================

Conversores Network ↔ dict para serialización JSON.
"""

from typing import Any, Dict, List

from ..core.graph import (
    Asset,
    AssetType,
    Branch,
    BranchType,
    Bus,
    BusType,
    VoltageLevel,
)
from ..core.network import Network


# =============================================================================
# Network → dict
# =============================================================================
def bus_to_dict(b: Bus) -> Dict[str, Any]:
    return {
        "id": b.id,
        "geometry": [b.geometry[0], b.geometry[1]],
        "voltage_kv": b.voltage_kv,
        "level": b.level.name,
        "bus_type": b.bus_type.name,
        "elevation_m": b.elevation_m,
        "zone": b.zone,
    }


def branch_to_dict(br: Branch) -> Dict[str, Any]:
    return {
        "id": br.id,
        "bus_from": br.bus_from,
        "bus_to": br.bus_to,
        "branch_type": br.branch_type.name,
        "geometry": [[x, y] for x, y in br.geometry],
        "length_m": br.length_m,
        "r_ohm": br.r_ohm,
        "x_ohm": br.x_ohm,
        "b_us": br.b_us,
        "rated_a": br.rated_a,
        "conductor_type": br.conductor_type,
        "span_max_m": br.span_max_m,
        "kva": br.kva,
        "kv_primary": br.kv_primary,
        "kv_secondary": br.kv_secondary,
        "connection": br.connection,
        "impedance_pu": br.impedance_pu,
        "is_open": br.is_open,
        "rated_ka_break": br.rated_ka_break,
    }


def asset_to_dict(a: Asset) -> Dict[str, Any]:
    return {
        "id": a.id,
        "bus_id": a.bus_id,
        "asset_type": a.asset_type.name,
        "rated_kw": a.rated_kw,
        "rated_kvar": a.rated_kvar,
        "profile_24h_kw": a.profile_24h_kw,
        "profile_annual_kwh": a.profile_annual_kwh,
        "controllable": a.controllable,
        "bidirectional": a.bidirectional,
        "capacity_kwh": a.capacity_kwh,
        "soc_initial": a.soc_initial,
        "efficiency_charge": a.efficiency_charge,
        "efficiency_discharge": a.efficiency_discharge,
        "capacity_factor": a.capacity_factor,
        "generation_profile": a.generation_profile,
        # Atributos socioeconómicos
        "socioeconomic_stratum": a.socioeconomic_stratum,
        "has_roof_pv_potential": a.has_roof_pv_potential,
        "roof_area_m2": a.roof_area_m2,
    }


def network_to_dict(net: Network) -> Dict[str, Any]:
    return {
        "name": net.name,
        "buses": [bus_to_dict(b) for b in net.buses.values()],
        "branches": [branch_to_dict(b) for b in net.branches.values()],
        "assets": [asset_to_dict(a) for a in net.assets.values()],
    }


# =============================================================================
# dict → Network
# =============================================================================
def dict_to_bus(d: Dict[str, Any]) -> Bus:
    return Bus(
        id=str(d["id"]),
        geometry=(float(d["geometry"][0]), float(d["geometry"][1])),
        voltage_kv=float(d["voltage_kv"]),
        level=VoltageLevel[d["level"]],
        bus_type=BusType[d["bus_type"]],
        elevation_m=float(d.get("elevation_m", 0.0)),
        zone=d.get("zone"),
    )


def dict_to_branch(d: Dict[str, Any]) -> Branch:
    return Branch(
        id=str(d["id"]),
        bus_from=str(d["bus_from"]),
        bus_to=str(d["bus_to"]),
        branch_type=BranchType[d["branch_type"]],
        geometry=[(float(x), float(y)) for x, y in d.get("geometry", [])],
        length_m=float(d.get("length_m", 0.0)),
        r_ohm=float(d.get("r_ohm", 0.0)),
        x_ohm=float(d.get("x_ohm", 0.0)),
        b_us=float(d.get("b_us", 0.0)),
        rated_a=float(d.get("rated_a", 0.0)),
        conductor_type=d.get("conductor_type"),
        span_max_m=d.get("span_max_m"),
        kva=d.get("kva"),
        kv_primary=d.get("kv_primary"),
        kv_secondary=d.get("kv_secondary"),
        connection=d.get("connection"),
        impedance_pu=d.get("impedance_pu"),
        is_open=bool(d.get("is_open", False)),
        rated_ka_break=d.get("rated_ka_break"),
    )


def dict_to_asset(d: Dict[str, Any]) -> Asset:
    s = d.get("socioeconomic_stratum")
    return Asset(
        id=str(d["id"]),
        bus_id=str(d["bus_id"]),
        asset_type=AssetType[d["asset_type"]],
        rated_kw=float(d["rated_kw"]),
        rated_kvar=float(d.get("rated_kvar", 0.0)),
        profile_24h_kw=d.get("profile_24h_kw"),
        profile_annual_kwh=d.get("profile_annual_kwh"),
        controllable=bool(d.get("controllable", False)),
        bidirectional=bool(d.get("bidirectional", False)),
        capacity_kwh=d.get("capacity_kwh"),
        soc_initial=d.get("soc_initial"),
        efficiency_charge=d.get("efficiency_charge"),
        efficiency_discharge=d.get("efficiency_discharge"),
        capacity_factor=d.get("capacity_factor"),
        generation_profile=d.get("generation_profile"),
        socioeconomic_stratum=int(s) if s is not None else None,
        has_roof_pv_potential=(
            bool(roof) if (roof := d.get("has_roof_pv_potential")) is not None
            else None
        ),
        roof_area_m2=(
            float(area) if (area := d.get("roof_area_m2")) is not None
            else None
        ),
    )


def dict_to_network(d: Dict[str, Any]) -> Network:
    net = Network(name=d.get("name", "Unnamed"))
    for bd in d.get("buses", []):
        net.add_bus(dict_to_bus(bd))
    for bd in d.get("branches", []):
        net.add_branch(dict_to_branch(bd))
    for ad in d.get("assets", []):
        net.add_asset(dict_to_asset(ad))
    return net
