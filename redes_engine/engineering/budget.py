# -*- coding: utf-8 -*-
"""
redes_engine.engineering.budget
================================

Motor de presupuesto UP → UC → BOM (Bill of Materials).

Conceptos (manuales EEQ B-01 / B-11 / B-14):
    - UP (Unidad de Propiedad): elemento físico estandarizado
        (poste, transformador, recloser…). Cada UP tiene un código.
    - UC (Unidad Constructiva): receta de UPs + materiales granulares
        que componen un montaje completo.
    - BOM (Bill of Materials): lista plana de todos los materiales
        necesarios + cantidades + precios.

Flujo:
    1. La red GIS aporta UPs (1 poste, 3 trafos, 50 tramos, ...)
    2. Cada UP se "explota" a sus UCs componentes via uc_database
    3. Cada UC se explota a materiales granulares (tornillos, abrazaderas, etc.)
    4. Se suma todo + se aplican precios → BOM final
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# =============================================================================
# Estructuras de datos
# =============================================================================
@dataclass
class UPItem:
    """Una Unidad de Propiedad instanciada en la red."""
    code: str                       # ej. "PSC-12500"
    quantity: int = 1
    description: str = ""
    voltage_level: str = "MT"


@dataclass
class UCItem:
    """Una Unidad Constructiva (receta de materiales)."""
    code: str
    description: str
    materials: List[Dict] = field(default_factory=list)
    # cada material: {"item": str, "descripcion": str, "unidad": str, "cantidad": float}
    cost_per_unit: Optional[float] = None


@dataclass
class BOMItem:
    """Una línea del Bill of Materials final."""
    item_code: str
    description: str
    unit: str
    quantity: float
    unit_price: float = 0.0

    @property
    def total(self) -> float:
        return self.quantity * self.unit_price


@dataclass
class BOMResult:
    """BOM consolidado completo."""
    items: Dict[str, BOMItem] = field(default_factory=dict)
    total_cost: float = 0.0
    n_items_unique: int = 0
    n_ups_processed: int = 0

    def add_material(
        self,
        item_code: str,
        description: str,
        unit: str,
        quantity: float,
        unit_price: float = 0.0,
    ) -> None:
        if item_code in self.items:
            self.items[item_code].quantity += quantity
        else:
            self.items[item_code] = BOMItem(
                item_code=item_code,
                description=description,
                unit=unit,
                quantity=quantity,
                unit_price=unit_price,
            )

    def finalize(self) -> None:
        self.n_items_unique = len(self.items)
        self.total_cost = sum(it.total for it in self.items.values())

    def summary(self) -> str:
        lines = [
            "═" * 64,
            "  PRESUPUESTO — BOM CONSOLIDADO",
            "═" * 64,
            f"  UPs procesadas      : {self.n_ups_processed}",
            f"  Items únicos        : {self.n_items_unique}",
            f"  Costo total         : ${self.total_cost:,.2f}",
            "─" * 64,
        ]
        # Top 10 ítems más costosos
        sorted_items = sorted(
            self.items.values(), key=lambda i: -i.total,
        )[:10]
        lines.append("  Top 10 ítems por costo:")
        for it in sorted_items:
            lines.append(
                f"    {it.item_code:<14} {it.description[:30]:<30} "
                f"{it.quantity:>8.2f} {it.unit:<5} "
                f"${it.unit_price:>8.2f} = ${it.total:>10,.2f}"
            )
        return "\n".join(lines)


# =============================================================================
# Motor
# =============================================================================
class BudgetEngine:
    """
    Motor de presupuesto que explota UPs a BOM consolidado.

    Uso típico:
        engine = BudgetEngine(uc_database, prices_database)
        bom = engine.compute_bom([
            UPItem(code="PSC-12500", quantity=1),
            UPItem(code="TRA-75-MT", quantity=2),
        ])
        print(bom.summary())
    """

    def __init__(
        self,
        uc_database: Optional[Dict[str, dict]] = None,
        prices_database: Optional[Dict[str, float]] = None,
    ):
        """
        Parameters
        ----------
        uc_database : dict
            {up_code: {description, materials: [...]}}
        prices_database : dict
            {item_code: unit_price_usd}
        """
        self.uc_database = uc_database or {}
        self.prices_database = prices_database or {}

    @classmethod
    def from_json_files(cls, uc_json_path: str,
                          prices_json_path: Optional[str] = None) -> "BudgetEngine":
        import json
        with open(uc_json_path, "r", encoding="utf-8") as f:
            uc = json.load(f)
        prices = {}
        if prices_json_path:
            with open(prices_json_path, "r", encoding="utf-8") as f:
                prices = json.load(f)
        return cls(uc, prices)

    def compute_bom(self, ups: List[UPItem]) -> BOMResult:
        """Procesa una lista de UPs y produce el BOM consolidado."""
        result = BOMResult()
        for up in ups:
            self._explode_up(up, result)
        result.finalize()
        return result

    def _explode_up(self, up: UPItem, result: BOMResult) -> None:
        """Explota una UP a sus materiales granulares."""
        # Buscar la UP en el catálogo
        up_def = self.uc_database.get(up.code)
        if up_def is None:
            # Buscar por categorías anidadas (POSTES, TRAFOS, etc.)
            for category in self.uc_database.values():
                if isinstance(category, dict) and up.code in category:
                    up_def = category[up.code]
                    break

        if up_def is None:
            # No hay receta — agregar como ítem genérico
            result.add_material(
                item_code=up.code,
                description=up.description or f"UP {up.code}",
                unit="u",
                quantity=up.quantity,
                unit_price=self.prices_database.get(up.code, 0.0),
            )
            result.n_ups_processed += up.quantity
            return

        # Explotar materiales
        materials = up_def.get("materials", [])
        for mat in materials:
            qty_per_up = float(mat.get("cantidad", 1))
            total_qty = qty_per_up * up.quantity
            item_code = str(mat.get("item", ""))
            unit_price = self.prices_database.get(item_code, 0.0)
            result.add_material(
                item_code=item_code,
                description=mat.get("descripcion", ""),
                unit=mat.get("unidad", "u"),
                quantity=total_qty,
                unit_price=unit_price,
            )
        result.n_ups_processed += up.quantity
