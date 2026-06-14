# -*- coding: utf-8 -*-
"""
redes_engine.core.network
==========================

Clase Network — contenedor del grafo eléctrico unificado.

Provee operaciones de consulta y validación topológica, sin
implementar el motor de flujo de potencia (delegado a OpenDSS).
"""

from collections import defaultdict, deque
from typing import Dict, List, Optional, Set

from .graph import (
    Asset,
    AssetType,
    Branch,
    BranchType,
    Bus,
    BusType,
    VoltageLevel,
)


class Network:
    """
    Grafo eléctrico unificado.

    Mantiene índices internos para búsquedas eficientes:
        - buses_by_id
        - branches_by_bus  (bus_id -> [branch_ids])
        - assets_by_bus    (bus_id -> [asset_ids])
    """

    def __init__(self, name: str = "Red"):
        self.name: str = name
        self.buses: Dict[str, Bus] = {}
        self.branches: Dict[str, Branch] = {}
        self.assets: Dict[str, Asset] = {}
        # Índices invertidos
        self._branches_by_bus: Dict[str, List[str]] = defaultdict(list)
        self._assets_by_bus: Dict[str, List[str]] = defaultdict(list)

    # =========================================================================
    # AGREGACIÓN
    # =========================================================================

    def add_bus(self, bus: Bus) -> Bus:
        if bus.id in self.buses:
            raise ValueError(f"Bus '{bus.id}' ya existe en la red.")
        self.buses[bus.id] = bus
        return bus

    def add_branch(self, branch: Branch) -> Branch:
        if branch.id in self.branches:
            raise ValueError(f"Branch '{branch.id}' ya existe en la red.")
        if branch.bus_from not in self.buses:
            raise ValueError(
                f"Branch '{branch.id}': bus_from '{branch.bus_from}' no existe."
            )
        if branch.bus_to not in self.buses:
            raise ValueError(
                f"Branch '{branch.id}': bus_to '{branch.bus_to}' no existe."
            )
        # Validación de transformador: voltajes distintos en sus extremos
        if branch.is_transformer():
            v_from = self.buses[branch.bus_from].voltage_kv
            v_to = self.buses[branch.bus_to].voltage_kv
            if abs(v_from - v_to) < 1e-6:
                raise ValueError(
                    f"Transformer '{branch.id}': voltajes iguales en ambos "
                    f"extremos ({v_from} kV). ¿Es realmente un transformador?"
                )

        self.branches[branch.id] = branch
        self._branches_by_bus[branch.bus_from].append(branch.id)
        self._branches_by_bus[branch.bus_to].append(branch.id)
        return branch

    def add_asset(self, asset: Asset) -> Asset:
        if asset.id in self.assets:
            raise ValueError(f"Asset '{asset.id}' ya existe en la red.")
        if asset.bus_id not in self.buses:
            raise ValueError(
                f"Asset '{asset.id}': bus '{asset.bus_id}' no existe."
            )
        # Validación BESS / V2G: deben tener capacity_kwh
        if asset.is_storage() and asset.capacity_kwh is None:
            raise ValueError(
                f"Asset '{asset.id}' es almacenamiento — debe definir capacity_kwh."
            )

        self.assets[asset.id] = asset
        self._assets_by_bus[asset.bus_id].append(asset.id)
        return asset

    # =========================================================================
    # CONSULTAS
    # =========================================================================

    def assets_at_bus(self, bus_id: str) -> List[Asset]:
        """Lista de assets conectados a un bus."""
        return [self.assets[aid] for aid in self._assets_by_bus.get(bus_id, [])]

    def branches_at_bus(self, bus_id: str) -> List[Branch]:
        """Lista de branches incidentes a un bus."""
        return [self.branches[bid] for bid in self._branches_by_bus.get(bus_id, [])]

    def assets_by_type(self, asset_type: AssetType) -> List[Asset]:
        return [a for a in self.assets.values() if a.asset_type == asset_type]

    def buses_by_level(self, level: VoltageLevel) -> List[Bus]:
        return [b for b in self.buses.values() if b.level == level]

    def neighbors(self, bus_id: str) -> List[str]:
        """Buses vecinos (a través de cualquier branch incidente)."""
        nbrs = []
        for bid in self._branches_by_bus.get(bus_id, []):
            br = self.branches[bid]
            other = br.bus_to if br.bus_from == bus_id else br.bus_from
            nbrs.append(other)
        return nbrs

    def transformers(self) -> List[Branch]:
        """Lista de todos los transformadores (puntos de cambio de voltaje)."""
        return [b for b in self.branches.values() if b.is_transformer()]

    def lines(self) -> List[Branch]:
        return [b for b in self.branches.values() if b.is_line()]

    # =========================================================================
    # ANÁLISIS TOPOLÓGICO
    # =========================================================================

    def is_connected(self) -> bool:
        """¿Toda la red es un único componente conexo?"""
        if not self.buses:
            return True
        start = next(iter(self.buses))
        visited = self._bfs(start)
        return len(visited) == len(self.buses)

    def connected_components(self) -> List[Set[str]]:
        """Devuelve los componentes conexos de la red."""
        visited_global: Set[str] = set()
        components: List[Set[str]] = []
        for bus_id in self.buses:
            if bus_id not in visited_global:
                comp = self._bfs(bus_id)
                components.append(comp)
                visited_global |= comp
        return components

    def _bfs(self, start: str) -> Set[str]:
        """Breadth-first search desde un bus inicial."""
        visited: Set[str] = {start}
        queue: deque = deque([start])
        while queue:
            current = queue.popleft()
            for nb in self.neighbors(current):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        return visited

    def find_root_bus(self) -> Optional[Bus]:
        """
        Identifica el bus 'raíz' del sistema (mayor voltaje).
        Útil para ubicar la fuente en simulación de flujo de potencia.
        """
        if not self.buses:
            return None
        return max(self.buses.values(), key=lambda b: b.voltage_kv)

    def path(self, bus_from: str, bus_to: str) -> Optional[List[str]]:
        """
        Encuentra un camino entre dos buses (BFS).
        Retorna la lista de bus_ids del camino o None si no hay conexión.
        """
        if bus_from not in self.buses or bus_to not in self.buses:
            return None
        if bus_from == bus_to:
            return [bus_from]

        prev: Dict[str, Optional[str]] = {bus_from: None}
        queue: deque = deque([bus_from])
        while queue:
            current = queue.popleft()
            if current == bus_to:
                # Reconstruir camino
                path = []
                node: Optional[str] = current
                while node is not None:
                    path.append(node)
                    node = prev[node]
                return list(reversed(path))
            for nb in self.neighbors(current):
                if nb not in prev:
                    prev[nb] = current
                    queue.append(nb)
        return None

    # =========================================================================
    # ESTADÍSTICAS
    # =========================================================================

    def total_load_kw(self, hour: Optional[int] = None) -> float:
        """
        Suma de potencia consumida por cargas y cargadores VE.

        Excluye el almacenamiento bidireccional (BESS / V2G): su potencia neta
        depende del despacho (puede inyectar), así que contarlo como "demanda"
        contaminaría el total. El almacenamiento se modela vía el dispatcher.
        """
        total = 0.0
        for a in self.assets.values():
            if (a.is_load() or a.is_ev()) and not a.is_storage():
                total += a.power_at_hour(hour) if hour is not None else a.rated_kw
        return total

    def total_generation_kw(self, hour: Optional[int] = None) -> float:
        """Suma de potencia generada (PV, eólico, cogen)."""
        total = 0.0
        for a in self.assets.values():
            if a.is_generator():
                if hour is not None and a.generation_profile and 0 <= hour < 24:
                    total += a.generation_profile[hour]
                else:
                    total += a.rated_kw
        return total

    def total_storage_kwh(self) -> float:
        """Capacidad total de almacenamiento instalada."""
        return sum(
            (a.capacity_kwh or 0.0)
            for a in self.assets.values()
            if a.is_storage()
        )

    def summary(self) -> str:
        """Resumen ejecutivo en texto."""
        lines = [
            f"════════════════════════════════════════════════════",
            f"  Red: {self.name}",
            f"════════════════════════════════════════════════════",
            f"  Buses        : {len(self.buses)}",
            f"    └─ MT      : {sum(1 for b in self.buses.values() if b.is_mt())}",
            f"    └─ BT      : {sum(1 for b in self.buses.values() if b.is_bt())}",
            f"  Branches     : {len(self.branches)}",
            f"    └─ Líneas  : {len(self.lines())}",
            f"    └─ Trafos  : {len(self.transformers())}",
            f"  Assets       : {len(self.assets)}",
            f"    └─ Cargas  : {sum(1 for a in self.assets.values() if a.is_load())}",
            f"    └─ VE      : {sum(1 for a in self.assets.values() if a.is_ev())}",
            f"    └─ PV      : {sum(1 for a in self.assets.values() if a.is_pv())}",
            f"    └─ BESS    : {sum(1 for a in self.assets.values() if a.is_storage())}",
            f"  Demanda nom. : {self.total_load_kw():.2f} kW",
            f"  Generación   : {self.total_generation_kw():.2f} kW",
            f"  BESS total   : {self.total_storage_kwh():.2f} kWh",
            f"  Topología    : {'✅ conexa' if self.is_connected() else '⚠ desconectada'}",
            f"════════════════════════════════════════════════════",
        ]
        return "\n".join(lines)
