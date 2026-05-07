# -*- coding: utf-8 -*-
"""
redes_engine.catalogs
======================

Catálogos de productos comerciales reales:
    - Cargadores VE (ABB Terra, Tesla Wall Connector, Wallbox, BYD, ...)
    - Sistemas BESS (Tesla Powerwall/Megapack, BYD, CATL, Sungrow, ...)

Permite materializar Assets con specs realistas (eficiencias, costos, ciclos).
"""

from .bess_systems import BESSCatalog, BESSProduct
from .ev_chargers import EVChargerCatalog, EVChargerProduct

__all__ = [
    "EVChargerCatalog", "EVChargerProduct",
    "BESSCatalog", "BESSProduct",
]
