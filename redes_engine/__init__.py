# -*- coding: utf-8 -*-
"""
redes_engine — Motor de cálculo de redes eléctricas de distribución.

Paquete independiente de QGIS que provee:
  - Grafo unificado multivoltaje (MT + BT + Trafo + Soterrado)
  - Modelos de assets (cargas, VE, PV, BESS, V2G)
  - Exportación a OpenDSS para análisis de flujos de potencia
  - Optimización MILP de dispatch BESS y carga inteligente de VE

Uso típico:
    from redes_engine import Network, Bus, Branch, Asset
    net = Network("MiRed")
    net.add_bus(...)
    net.add_branch(...)
    net.add_asset(...)
"""

from .core.graph import (
    Asset,
    AssetType,
    Branch,
    BranchType,
    Bus,
    BusType,
    VoltageLevel,
)
from .core.network import Network

__version__ = "0.1.0"
__all__ = [
    "Bus", "Branch", "Asset",
    "VoltageLevel", "BusType", "BranchType", "AssetType",
    "Network",
]
