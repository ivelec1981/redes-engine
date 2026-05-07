# -*- coding: utf-8 -*-
"""
redes_engine.api.storage
=========================

Almacenamiento en memoria para el prototipo. En producción:
    - PostgreSQL + PostGIS para geometrías
    - Redis para resultados cacheados
    - S3 para archivos grandes

Para el prototipo basta un singleton dict-based con thread-safety.
"""

import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# =============================================================================
# Entidad almacenada
# =============================================================================
@dataclass
class StoredNetwork:
    """Network + metadatos guardados en memoria."""
    id: str
    name: str
    network: object                # redes_engine.Network
    crs: str = "EPSG:32717"
    last_solve_result: object = None         # PowerFlowResult
    last_compliance_report: object = None    # ComplianceReport
    last_hosting_results: object = None      # HostingCapacityResults
    last_annual_results: object = None       # AnnualResults
    layers_geojson: Dict[str, dict] = field(default_factory=dict)


# =============================================================================
# Store Singleton
# =============================================================================
class NetworkStore:
    """
    Almacén en memoria de redes activas. Thread-safe.

    Diseñado para sustitución directa por una BDD real.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._items: Dict[str, StoredNetwork] = {}

    # =========================================================================
    # CRUD
    # =========================================================================
    def create(
        self,
        name: str,
        network: object,
        crs: str = "EPSG:32717",
        layers_geojson: Optional[Dict[str, dict]] = None,
    ) -> StoredNetwork:
        nid = uuid.uuid4().hex[:12]
        with self._lock:
            stored = StoredNetwork(
                id=nid,
                name=name,
                network=network,
                crs=crs,
                layers_geojson=layers_geojson or {},
            )
            self._items[nid] = stored
            return stored

    def get(self, network_id: str) -> Optional[StoredNetwork]:
        with self._lock:
            return self._items.get(network_id)

    def list_all(self) -> List[StoredNetwork]:
        with self._lock:
            return list(self._items.values())

    def delete(self, network_id: str) -> bool:
        with self._lock:
            return self._items.pop(network_id, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


# Singleton del proceso
_global_store: Optional[NetworkStore] = None


def get_store() -> NetworkStore:
    """Devuelve el store global (lazy-init)."""
    global _global_store
    if _global_store is None:
        _global_store = NetworkStore()
    return _global_store
