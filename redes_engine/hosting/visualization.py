# -*- coding: utf-8 -*-
"""
redes_engine.hosting.visualization
====================================

Exporta resultados de Host Capacity a:
    - Tabla ranking en texto
    - GeoJSON con simbología graduada (rojo→verde según capacidad)
    - QML para QGIS
"""

import json
import os
from typing import List, Optional

from ..core.network import Network
from .results import (
    BusHostingCapacity,
    HostingCapacityResults,
    LimitingFactor,
)


# =============================================================================
# Tabla de ranking
# =============================================================================
def hosting_ranking_table(
    results: HostingCapacityResults,
    n: int = 20,
    sort_by: str = "pv",
) -> str:
    """
    Imprime ranking de buses por capacidad de alojamiento.

    sort_by: "pv" | "load" | "total"
    """
    if sort_by == "pv":
        bus_list = sorted(
            results.bus_results.values(), key=lambda b: -b.pv_hosting_kw
        )
    elif sort_by == "load":
        bus_list = sorted(
            results.bus_results.values(), key=lambda b: -b.load_hosting_kw
        )
    else:
        bus_list = sorted(
            results.bus_results.values(),
            key=lambda b: -(b.pv_hosting_kw + b.load_hosting_kw),
        )

    lines = [
        "",
        f"  HOST CAPACITY RANKING — sorted by {sort_by.upper()}",
        "  " + "─" * 90,
        f"  {'Bus':<14} {'V nom':>7} "
        f"{'PV kW':>10} {'PV limit':>22} "
        f"{'Load kW':>10} {'Load limit':>22}",
        "  " + "─" * 90,
    ]
    for b in bus_list[:n]:
        lines.append(
            f"  {b.bus_id:<14} {b.voltage_nominal_kv:>6.2f}kV "
            f"{b.pv_hosting_kw:>9.1f} {b.pv_limiting_factor.value:>22} "
            f"{b.load_hosting_kw:>9.1f} {b.load_limiting_factor.value:>22}"
        )
    return "\n".join(lines)


# =============================================================================
# GeoJSON + QML para QGIS
# =============================================================================
def write_hosting_geojson(
    network: Network,
    results: HostingCapacityResults,
    output_dir: str,
    crs: str = "EPSG:32717",
) -> dict:
    """
    Genera capa GeoJSON con resultados de hosting + QML graduado.

    Salida:
        output_dir/
        ├── hosting_capacity.geojson
        ├── hosting_capacity_pv.qml      ← simbología por capacidad PV
        └── hosting_capacity_load.qml    ← simbología por capacidad de carga
    """
    os.makedirs(output_dir, exist_ok=True)

    # 1. GeoJSON
    features = []
    for bus_id, cap in results.bus_results.items():
        bus = network.buses.get(bus_id)
        if bus is None:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "id": cap.bus_id,
                "voltage_nominal_kv": cap.voltage_nominal_kv,
                "pv_hosting_kw": round(cap.pv_hosting_kw, 2),
                "pv_limit": cap.pv_limiting_factor.value,
                "pv_limit_hour": cap.pv_limiting_hour or -1,
                "pv_limit_element": cap.pv_limiting_element,
                "load_hosting_kw": round(cap.load_hosting_kw, 2),
                "load_limit": cap.load_limiting_factor.value,
                "load_limit_hour": cap.load_limiting_hour or -1,
                "load_limit_element": cap.load_limiting_element,
                "total_iterations": cap.total_iterations(),
            },
            "geometry": {
                "type": "Point",
                "coordinates": [bus.geometry[0], bus.geometry[1]],
            },
        })

    crs_part = crs.split(":")[-1] if ":" in crs else crs
    geojson_data = {
        "type": "FeatureCollection",
        "name": "Hosting Capacity",
        "crs": {
            "type": "name",
            "properties": {"name": f"urn:ogc:def:crs:EPSG::{crs_part}"},
        },
        "features": features,
    }
    geojson_path = os.path.join(output_dir, "hosting_capacity.geojson")
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(geojson_data, f, ensure_ascii=False, indent=2)

    # 2. QML para PV
    pv_qml_path = os.path.join(output_dir, "hosting_capacity_pv.qml")
    with open(pv_qml_path, "w", encoding="utf-8") as f:
        f.write(_qml_graduated_pv())

    # 3. QML para carga
    load_qml_path = os.path.join(output_dir, "hosting_capacity_load.qml")
    with open(load_qml_path, "w", encoding="utf-8") as f:
        f.write(_qml_graduated_load())

    return {
        "geojson": geojson_path,
        "qml_pv": pv_qml_path,
        "qml_load": load_qml_path,
    }


# =============================================================================
# QML templates (sin dependencia de QGIS)
# =============================================================================
def _qml_graduated_pv() -> str:
    """Simbología graduada por pv_hosting_kw: rojo (saturado) → verde (libre)."""
    return '''<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28" styleCategories="Symbology|Labeling">
  <renderer-v2 forceraster="0" type="graduatedSymbol" attr="pv_hosting_kw" graduatedMethod="GraduatedColor">
    <ranges>
      <range lower="0.0" upper="10.0" symbol="0" label="0-10 kW (saturado)" render="true"/>
      <range lower="10.0" upper="50.0" symbol="1" label="10-50 kW (limitado)" render="true"/>
      <range lower="50.0" upper="200.0" symbol="2" label="50-200 kW (medio)" render="true"/>
      <range lower="200.0" upper="500.0" symbol="3" label="200-500 kW (amplio)" render="true"/>
      <range lower="500.0" upper="9999.0" symbol="4" label=">500 kW (sin límite)" render="true"/>
    </ranges>
    <symbols>
      <symbol type="marker" name="0">
        <layer class="SimpleMarker">
          <Option type="Map">
            <Option name="color" type="QString" value="192,57,43,255"/>
            <Option name="name" type="QString" value="circle"/>
            <Option name="outline_color" type="QString" value="44,62,80,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
            <Option name="size" type="QString" value="3.0"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="marker" name="1">
        <layer class="SimpleMarker">
          <Option type="Map">
            <Option name="color" type="QString" value="230,126,34,255"/>
            <Option name="name" type="QString" value="circle"/>
            <Option name="outline_color" type="QString" value="44,62,80,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
            <Option name="size" type="QString" value="3.5"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="marker" name="2">
        <layer class="SimpleMarker">
          <Option type="Map">
            <Option name="color" type="QString" value="241,196,15,255"/>
            <Option name="name" type="QString" value="circle"/>
            <Option name="outline_color" type="QString" value="44,62,80,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
            <Option name="size" type="QString" value="4.0"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="marker" name="3">
        <layer class="SimpleMarker">
          <Option type="Map">
            <Option name="color" type="QString" value="46,204,113,255"/>
            <Option name="name" type="QString" value="circle"/>
            <Option name="outline_color" type="QString" value="44,62,80,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
            <Option name="size" type="QString" value="4.5"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="marker" name="4">
        <layer class="SimpleMarker">
          <Option type="Map">
            <Option name="color" type="QString" value="39,174,96,255"/>
            <Option name="name" type="QString" value="circle"/>
            <Option name="outline_color" type="QString" value="44,62,80,255"/>
            <Option name="outline_width" type="QString" value="0.4"/>
            <Option name="size" type="QString" value="5.0"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
    <source-symbol>
      <symbol type="marker" name="source">
        <layer class="SimpleMarker">
          <Option type="Map">
            <Option name="color" type="QString" value="189,195,199,255"/>
            <Option name="name" type="QString" value="circle"/>
            <Option name="size" type="QString" value="3.0"/>
          </Option>
        </layer>
      </symbol>
    </source-symbol>
  </renderer-v2>
  <labeling type="simple">
    <settings>
      <text-style fontFamily="Segoe UI" fontSize="8" textColor="44,62,80,255" fontWeight="50">
        <text-buffer bufferDraw="1" bufferSize="1" bufferColor="255,255,255,200"/>
      </text-style>
      <placement placement="2" dist="2"/>
      <text-format>
        <expression>concat("id", '\\n', round("pv_hosting_kw", 0), ' kW PV')</expression>
      </text-format>
    </settings>
  </labeling>
</qgis>'''


def _qml_graduated_load() -> str:
    """Simbología graduada por load_hosting_kw."""
    return _qml_graduated_pv().replace(
        'attr="pv_hosting_kw"', 'attr="load_hosting_kw"'
    ).replace(
        'kW PV', 'kW Load'
    ).replace(
        '0-10 kW (saturado)', '0-10 kW (saturado)'
    )
