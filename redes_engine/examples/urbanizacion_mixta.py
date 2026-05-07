# -*- coding: utf-8 -*-
"""
redes_engine.examples.urbanizacion_mixta
=========================================

Construye una urbanización mixta MT→Trafo→BT con:
    - 3 buses MT aéreos (22.8 kV)
    - 1 transformador trifásico 75 kVA (22.8/0.220 kV)
    - 5 buses BT (red subterránea)
    - 2 medidores residenciales (con PV + BESS + VE)
    - 1 área comunal (alumbrado + cargador rápido + BESS comunitario)

Demuestra:
    ✓ Cómo MT y BT viven en UN SOLO grafo
    ✓ Cómo VE, PV y BESS se enganchan como Assets
    ✓ Cómo se exporta todo a un .dss listo para OpenDSS
"""

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
from ..io.opendss_bridge import OpenDSSExporter


def build_urbanizacion_pastaza() -> Network:
    """Arma la red de ejemplo de la urbanización El Pastaza."""
    net = Network(name="ElPastaza")

    # =========================================================================
    # 1. BUSES MT (22.8 kV) — Red aérea entrante desde alimentador
    # =========================================================================
    net.add_bus(Bus(
        id="Bus_001",
        geometry=(763500.0, 9680000.0),
        voltage_kv=22.8,
        level=VoltageLevel.MT_22_8KV,
        bus_type=BusType.POSTE_MT,
        zone="Alimentador-Pastaza-01",
    ))
    net.add_bus(Bus(
        id="Bus_002",
        geometry=(763580.0, 9680000.0),
        voltage_kv=22.8,
        level=VoltageLevel.MT_22_8KV,
        bus_type=BusType.POSTE_MT,
    ))
    net.add_bus(Bus(
        id="Bus_003",
        geometry=(763640.0, 9680000.0),
        voltage_kv=22.8,
        level=VoltageLevel.MT_22_8KV,
        bus_type=BusType.NODO_TRAFO,
    ))

    # =========================================================================
    # 2. BUSES BT (0.220 kV) — Red subterránea de la urbanización
    # =========================================================================
    net.add_bus(Bus(
        id="Bus_004",
        geometry=(763640.0, 9680005.0),
        voltage_kv=0.220,
        level=VoltageLevel.BT_220_127,
        bus_type=BusType.POZO_BT,
    ))
    net.add_bus(Bus(
        id="Bus_005",
        geometry=(763665.0, 9680010.0),
        voltage_kv=0.220,
        level=VoltageLevel.BT_220_127,
        bus_type=BusType.POZO_BT,
    ))
    net.add_bus(Bus(
        id="Bus_006",
        geometry=(763680.0, 9680040.0),
        voltage_kv=0.220,
        level=VoltageLevel.BT_220_127,
        bus_type=BusType.POZO_BT,
    ))
    net.add_bus(Bus(
        id="Bus_010",
        geometry=(763665.0, 9680020.0),
        voltage_kv=0.220,
        level=VoltageLevel.BT_220_127,
        bus_type=BusType.MEDIDOR,
    ))
    net.add_bus(Bus(
        id="Bus_011",
        geometry=(763665.0, 9680030.0),
        voltage_kv=0.220,
        level=VoltageLevel.BT_220_127,
        bus_type=BusType.MEDIDOR,
    ))

    # =========================================================================
    # 3. LÍNEAS MT AÉREAS (22.8 kV)
    # =========================================================================
    net.add_branch(Branch(
        id="L_001",
        bus_from="Bus_001", bus_to="Bus_002",
        branch_type=BranchType.LINE_AEREA_MT,
        geometry=[(763500, 9680000), (763580, 9680000)],
        length_m=80.0,
        r_ohm=0.21, x_ohm=0.32,
        rated_a=340.0,
        conductor_type="ACSR_4/0AWG",
    ))
    net.add_branch(Branch(
        id="L_002",
        bus_from="Bus_002", bus_to="Bus_003",
        branch_type=BranchType.LINE_AEREA_MT,
        geometry=[(763580, 9680000), (763640, 9680000)],
        length_m=60.0,
        r_ohm=0.16, x_ohm=0.24,
        rated_a=240.0,
        conductor_type="ACSR_1/0AWG",
    ))

    # =========================================================================
    # 4. TRANSFORMADOR — La arista que une MT con BT
    # =========================================================================
    net.add_branch(Branch(
        id="T_001",
        bus_from="Bus_003", bus_to="Bus_004",  # MT 22.8kV → BT 0.22kV
        branch_type=BranchType.TRANSFORMER,
        geometry=[(763640, 9680000), (763640, 9680005)],
        length_m=5.0,
        kva=75.0,
        kv_primary=22.8,
        kv_secondary=0.220,
        impedance_pu=0.04,        # 4% de impedancia
        connection="Dyn1",
        rated_a=197.0,
    ))

    # =========================================================================
    # 5. LÍNEAS BT SUBTERRÁNEAS
    # =========================================================================
    net.add_branch(Branch(
        id="L_003",
        bus_from="Bus_004", bus_to="Bus_005",
        branch_type=BranchType.LINE_SOTERRADA_BT,
        geometry=[(763640, 9680005), (763665, 9680010)],
        length_m=25.0,
        r_ohm=0.012, x_ohm=0.008,
        rated_a=200.0,
    ))
    net.add_branch(Branch(
        id="L_004",
        bus_from="Bus_005", bus_to="Bus_010",
        branch_type=BranchType.LINE_SOTERRADA_BT,
        geometry=[(763665, 9680010), (763665, 9680020)],
        length_m=10.0,
        r_ohm=0.005, x_ohm=0.003,
        rated_a=150.0,
    ))
    net.add_branch(Branch(
        id="L_005",
        bus_from="Bus_005", bus_to="Bus_011",
        branch_type=BranchType.LINE_SOTERRADA_BT,
        geometry=[(763665, 9680010), (763665, 9680030)],
        length_m=20.0,
        r_ohm=0.010, x_ohm=0.006,
        rated_a=150.0,
    ))
    net.add_branch(Branch(
        id="L_006",
        bus_from="Bus_004", bus_to="Bus_006",
        branch_type=BranchType.LINE_SOTERRADA_BT,
        geometry=[(763640, 9680005), (763680, 9680040)],
        length_m=40.0,
        r_ohm=0.020, x_ohm=0.013,
        rated_a=200.0,
    ))

    # =========================================================================
    # 6. ASSETS — Casa A: carga + PV + BESS + cargador VE Type 2
    # =========================================================================
    net.add_asset(Asset(
        id="LD_010",
        bus_id="Bus_010",
        asset_type=AssetType.LOAD_RESIDENCIAL,
        rated_kw=4.0,
        rated_kvar=1.3,
        # Perfil residencial típico (24h en kW)
        profile_24h_kw=[
            0.8, 0.7, 0.6, 0.6, 0.7, 0.9,   # 0-5  madrugada
            1.5, 2.5, 2.0, 1.2, 1.0, 1.2,   # 6-11 mañana
            1.8, 1.5, 1.2, 1.4, 2.5, 3.5,   # 12-17 tarde
            4.0, 3.8, 3.0, 2.0, 1.5, 1.0,   # 18-23 noche-pico
        ],
    ))
    net.add_asset(Asset(
        id="PV_010",
        bus_id="Bus_010",
        asset_type=AssetType.SOLAR_PV_RESID,
        rated_kw=5.0,
        controllable=False,
        capacity_factor=0.18,
        # Curva solar típica (sale a las 6, pico al mediodía)
        generation_profile=[
            0, 0, 0, 0, 0, 0,
            0.5, 1.5, 3.0, 4.0, 4.5, 5.0,
            5.0, 4.5, 3.5, 2.0, 0.8, 0,
            0, 0, 0, 0, 0, 0,
        ],
    ))
    net.add_asset(Asset(
        id="BS_010",
        bus_id="Bus_010",
        asset_type=AssetType.BESS_BTM,
        rated_kw=5.0,
        controllable=True,
        bidirectional=True,
        capacity_kwh=10.0,
        soc_initial=0.5,
        efficiency_charge=0.95,
        efficiency_discharge=0.95,
    ))
    net.add_asset(Asset(
        id="EV_010",
        bus_id="Bus_010",
        asset_type=AssetType.EV_CHARGER_AC_L2,
        rated_kw=7.4,
        controllable=True,
        # Carga programada de noche (19-23h)
        profile_24h_kw=[
            0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0,
            0, 0, 0, 0, 0, 0,
            3.7, 7.4, 7.4, 7.4, 3.7, 0,
        ],
    ))

    # =========================================================================
    # 7. ASSETS — Casa B: carga + V2G bidireccional
    # =========================================================================
    net.add_asset(Asset(
        id="LD_011",
        bus_id="Bus_011",
        asset_type=AssetType.LOAD_RESIDENCIAL,
        rated_kw=3.5,
        rated_kvar=1.1,
    ))
    net.add_asset(Asset(
        id="V2G_011",
        bus_id="Bus_011",
        asset_type=AssetType.V2G_BIDIRECTIONAL,
        rated_kw=11.0,
        capacity_kwh=60.0,
        controllable=True,
        bidirectional=True,
        soc_initial=0.7,
        efficiency_charge=0.92,
        efficiency_discharge=0.92,
    ))

    # =========================================================================
    # 8. ASSETS — Área comunal
    # =========================================================================
    net.add_asset(Asset(
        id="ALU_006",
        bus_id="Bus_006",
        asset_type=AssetType.ALUMBRADO_PUBLICO,
        rated_kw=1.6,
        # Solo de noche
        profile_24h_kw=[1.6]*6 + [0]*12 + [1.6]*6,
    ))
    net.add_asset(Asset(
        id="EVDC_006",
        bus_id="Bus_006",
        asset_type=AssetType.EV_CHARGER_DC_FAST,
        rated_kw=50.0,
        controllable=True,
    ))
    net.add_asset(Asset(
        id="BESS_006",
        bus_id="Bus_006",
        asset_type=AssetType.BESS_C_AND_I,
        rated_kw=25.0,
        capacity_kwh=50.0,
        controllable=True,
        bidirectional=True,
        soc_initial=0.5,
    ))

    return net


# =============================================================================
# ENTRADA EJECUTABLE
# =============================================================================
if __name__ == "__main__":
    import os

    print("Construyendo red 'El Pastaza'...")
    net = build_urbanizacion_pastaza()
    print(net.summary())

    # Verificar topología
    print(f"\nBus raíz (slack): {net.find_root_bus().id} "
          f"@ {net.find_root_bus().voltage_kv} kV")
    print(f"Trafos:          {[t.id for t in net.transformers()]}")
    print(f"Líneas:          {len(net.lines())}")

    # Camino de un poste de MT hasta un medidor de BT
    camino = net.path("Bus_001", "Bus_010")
    print(f"\nCamino Bus_001 → Bus_010: {' → '.join(camino) if camino else 'sin camino'}")

    # Exportar a OpenDSS
    output = os.path.join(os.path.dirname(__file__), "urbanizacion_pastaza.dss")
    exporter = OpenDSSExporter(net)
    exporter.export(output)
    print(f"\n✅ Exportado a OpenDSS: {output}")
