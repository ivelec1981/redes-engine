# -*- coding: utf-8 -*-
"""
redes_engine.catalogs.bess_systems
====================================

Catálogo de sistemas BESS comerciales reales.
"""

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..core.graph import Asset, AssetType

_CATEGORY_TO_ASSET_TYPE = {
    "bess_btm":         AssetType.BESS_BTM,
    "bess_ci":          AssetType.BESS_C_AND_I,
    "bess_grid_scale":  AssetType.BESS_GRID_SCALE,
    "pv_bess_hybrid":   AssetType.PV_BESS_HYBRID,
}


# =============================================================================
# Producto
# =============================================================================
@dataclass
class BESSProduct:
    """Especificaciones técnicas + comerciales de un BESS comercial."""
    model: str
    manufacturer: str
    category: str
    rated_kw: float
    capacity_kwh: float
    voltage_kv: float = 0.240
    round_trip_efficiency: float = 0.90
    cycle_life: int = 6000
    depth_of_discharge_pct: float = 100.0
    warranty_years: int = 10
    cost_usd_approx: float = 0.0
    notes: str = ""

    @property
    def duration_hours(self) -> float:
        """Duración nominal: capacity_kwh / rated_kw."""
        return self.capacity_kwh / self.rated_kw if self.rated_kw > 0 else 0.0

    @property
    def cost_per_kwh_usd(self) -> float:
        return (self.cost_usd_approx / self.capacity_kwh
                if self.capacity_kwh > 0 else 0.0)

    @property
    def usable_kwh(self) -> float:
        return self.capacity_kwh * self.depth_of_discharge_pct / 100.0

    @property
    def half_efficiency(self) -> float:
        """Eficiencia one-way ≈ √(round-trip)."""
        return math.sqrt(self.round_trip_efficiency)

    # =========================================================================
    # Conversión a Asset del motor
    # =========================================================================
    def to_asset(
        self,
        asset_id: str, bus_id: str,
        soc_initial: float = 0.5,
        controllable: bool = True,
    ) -> Asset:
        atype = _CATEGORY_TO_ASSET_TYPE.get(self.category)
        if atype is None:
            raise ValueError(f"Categoría desconocida: {self.category}")
        eff = self.half_efficiency
        return Asset(
            id=asset_id, bus_id=bus_id,
            asset_type=atype,
            rated_kw=self.rated_kw,
            capacity_kwh=self.capacity_kwh,
            controllable=controllable,
            bidirectional=True,
            soc_initial=soc_initial,
            efficiency_charge=eff,
            efficiency_discharge=eff,
        )


# =============================================================================
# Catálogo
# =============================================================================
class BESSCatalog:
    """Catálogo de productos BESS."""

    def __init__(self, products: List[BESSProduct]):
        self.products = products
        self._by_model: Dict[str, BESSProduct] = {
            p.model: p for p in products
        }

    @classmethod
    def load_default(cls) -> "BESSCatalog":
        path = os.path.join(
            os.path.dirname(__file__), "data", "bess_systems.json"
        )
        return cls.load_from_file(path)

    @classmethod
    def load_from_file(cls, path: str) -> "BESSCatalog":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        products = [
            BESSProduct(
                model=p["model"],
                manufacturer=p["manufacturer"],
                category=p["category"],
                rated_kw=float(p["rated_kw"]),
                capacity_kwh=float(p["capacity_kwh"]),
                voltage_kv=float(p.get("voltage_kv", 0.240)),
                round_trip_efficiency=float(p.get("round_trip_efficiency", 0.90)),
                cycle_life=int(p.get("cycle_life", 6000)),
                depth_of_discharge_pct=float(p.get("depth_of_discharge_pct", 100.0)),
                warranty_years=int(p.get("warranty_years", 10)),
                cost_usd_approx=float(p.get("cost_usd_approx", 0.0)),
                notes=p.get("notes", ""),
            )
            for p in data.get("products", [])
        ]
        return cls(products)

    # Búsqueda
    def find_by_model(self, model: str) -> Optional[BESSProduct]:
        return self._by_model.get(model)

    def filter_by_manufacturer(self, manufacturer: str) -> List[BESSProduct]:
        m = manufacturer.lower()
        return [p for p in self.products
                if p.manufacturer.lower() == m]

    def filter_by_category(self, category: str) -> List[BESSProduct]:
        return [p for p in self.products if p.category == category]

    def best_match(
        self, target_kwh: float, category: Optional[str] = None,
    ) -> Optional[BESSProduct]:
        """Encuentra el BESS más pequeño que cumpla con la capacidad target."""
        candidates = (self.filter_by_category(category)
                      if category else self.products)
        candidates = [p for p in candidates if p.capacity_kwh >= target_kwh]
        if not candidates:
            # Si nada cumple, devolver el más grande disponible
            return max(self.products, key=lambda p: p.capacity_kwh, default=None)
        return min(candidates, key=lambda p: p.capacity_kwh)

    def cheapest_per_kwh(self, category: Optional[str] = None) -> Optional[BESSProduct]:
        candidates = (self.filter_by_category(category)
                      if category else self.products)
        candidates = [p for p in candidates if p.cost_usd_approx > 0]
        if not candidates:
            return None
        return min(candidates, key=lambda p: p.cost_per_kwh_usd)

    def __len__(self) -> int:
        return len(self.products)

    def __iter__(self):
        return iter(self.products)

    def summary(self) -> str:
        manufacturers = sorted({p.manufacturer for p in self.products})
        return (
            f"BESSCatalog: {len(self.products)} products from "
            f"{len(manufacturers)} manufacturers ({', '.join(manufacturers)})."
        )
