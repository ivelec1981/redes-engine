# -*- coding: utf-8 -*-
"""
redes_engine.catalogs.ev_chargers
==================================

Catálogo de cargadores VE comerciales reales.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..core.graph import Asset, AssetType

# =============================================================================
# Mapeo categoría JSON → AssetType
# =============================================================================
_CATEGORY_TO_ASSET_TYPE = {
    "ev_ac_l1":           AssetType.EV_CHARGER_AC_L1,
    "ev_ac_l2":           AssetType.EV_CHARGER_AC_L2,
    "ev_dc_fast":         AssetType.EV_CHARGER_DC_FAST,
    "ev_dc_ultra":        AssetType.EV_CHARGER_DC_ULTRA,
    "ev_fleet_depot":     AssetType.EV_FLEET_DEPOT,
    "v2g_bidirectional":  AssetType.V2G_BIDIRECTIONAL,
}


# =============================================================================
# Producto
# =============================================================================
@dataclass
class EVChargerProduct:
    """Especificaciones técnicas + comerciales de un cargador VE real."""
    model: str
    manufacturer: str
    category: str               # ej: "ev_ac_l2", "ev_dc_fast"
    rated_kw: float
    voltage_kv: float
    phases: int
    current_a: float
    connector: str
    controllable: bool
    v2g_capable: bool
    efficiency: float = 0.95
    cost_usd_approx: float = 0.0
    notes: str = ""

    # =========================================================================
    # Conversión a Asset del motor
    # =========================================================================
    def to_asset(
        self,
        asset_id: str, bus_id: str,
        profile_24h_kw: Optional[List[float]] = None,
    ) -> Asset:
        """Materializa este producto como Asset enganchado a un bus."""
        atype = _CATEGORY_TO_ASSET_TYPE.get(self.category)
        if atype is None:
            raise ValueError(f"Categoría desconocida: {self.category}")

        # V2G es bidireccional y tiene capacidad efectiva del vehículo
        bidirectional = self.v2g_capable
        capacity_kwh = None
        if atype == AssetType.V2G_BIDIRECTIONAL:
            capacity_kwh = 60.0   # asume batería estándar 60 kWh

        return Asset(
            id=asset_id, bus_id=bus_id,
            asset_type=atype,
            rated_kw=self.rated_kw,
            controllable=self.controllable,
            bidirectional=bidirectional,
            capacity_kwh=capacity_kwh,
            efficiency_charge=self.efficiency,
            efficiency_discharge=self.efficiency,
            profile_24h_kw=profile_24h_kw,
        )

    @property
    def cost_per_kw_usd(self) -> float:
        return (self.cost_usd_approx / self.rated_kw
                if self.rated_kw > 0 else 0.0)


# =============================================================================
# Catálogo
# =============================================================================
class EVChargerCatalog:
    """Catálogo de productos cargadores VE."""

    def __init__(self, products: List[EVChargerProduct]):
        self.products = products
        self._by_model: Dict[str, EVChargerProduct] = {
            p.model: p for p in products
        }

    # =========================================================================
    # Constructores
    # =========================================================================
    @classmethod
    def load_default(cls) -> "EVChargerCatalog":
        """Carga el catálogo por defecto bundled con redes_engine."""
        path = os.path.join(
            os.path.dirname(__file__), "data", "ev_chargers.json"
        )
        return cls.load_from_file(path)

    @classmethod
    def load_from_file(cls, path: str) -> "EVChargerCatalog":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        products = [
            EVChargerProduct(
                model=p["model"],
                manufacturer=p["manufacturer"],
                category=p["category"],
                rated_kw=float(p["rated_kw"]),
                voltage_kv=float(p["voltage_kv"]),
                phases=int(p["phases"]),
                current_a=float(p["current_a"]),
                connector=p.get("connector", ""),
                controllable=bool(p.get("controllable", True)),
                v2g_capable=bool(p.get("v2g_capable", False)),
                efficiency=float(p.get("efficiency", 0.95)),
                cost_usd_approx=float(p.get("cost_usd_approx", 0.0)),
                notes=p.get("notes", ""),
            )
            for p in data.get("products", [])
        ]
        return cls(products)

    # =========================================================================
    # Búsqueda y filtrado
    # =========================================================================
    def find_by_model(self, model: str) -> Optional[EVChargerProduct]:
        return self._by_model.get(model)

    def filter_by_manufacturer(self, manufacturer: str) -> List[EVChargerProduct]:
        m = manufacturer.lower()
        return [p for p in self.products
                if p.manufacturer.lower() == m]

    def filter_by_category(self, category: str) -> List[EVChargerProduct]:
        return [p for p in self.products if p.category == category]

    def filter_by_kw_range(self, min_kw: float, max_kw: float) -> List[EVChargerProduct]:
        return [p for p in self.products
                if min_kw <= p.rated_kw <= max_kw]

    def v2g_products(self) -> List[EVChargerProduct]:
        return [p for p in self.products if p.v2g_capable]

    def cheapest_per_kw(self, category: Optional[str] = None) -> Optional[EVChargerProduct]:
        candidates = (self.filter_by_category(category)
                      if category else self.products)
        candidates = [p for p in candidates if p.cost_usd_approx > 0]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.cost_per_kw_usd)

    def __len__(self) -> int:
        return len(self.products)

    def __iter__(self):
        return iter(self.products)

    def summary(self) -> str:
        manufacturers = sorted({p.manufacturer for p in self.products})
        categories = sorted({p.category for p in self.products})
        return (
            f"EVChargerCatalog: {len(self.products)} products from "
            f"{len(manufacturers)} manufacturers ({', '.join(manufacturers)}). "
            f"Categories: {', '.join(categories)}"
        )
