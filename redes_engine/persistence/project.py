# -*- coding: utf-8 -*-
"""
redes_engine.persistence.project
==================================

Formato `.rsproj` — JSON con metadatos + Network completo.

Estructura:
{
  "format_version": "1.0",
  "engine_version": "0.1.0",
  "metadata": {
      "name": "El Pastaza",
      "created_at": "2026-05-06T...",
      "modified_at": "2026-05-06T...",
      "author": "Ing. Juan Pérez",
      "description": "...",
      "crs": "EPSG:32717",
      "tags": ["Pastaza", "Pastaza-01"]
  },
  "network": {
      "name": "El Pastaza",
      "buses": [...],
      "branches": [...],
      "assets": [...]
  }
}
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..core.network import Network
from .serialization import dict_to_network, network_to_dict

CURRENT_FORMAT_VERSION = "1.0"


# =============================================================================
# Errores específicos
# =============================================================================
class RSProjectError(Exception):
    """Error al cargar/guardar un proyecto .rsproj."""


# =============================================================================
# Metadatos
# =============================================================================
@dataclass
class RSProjectMetadata:
    name: str = ""
    description: str = ""
    author: str = ""
    company: str = ""
    crs: str = "EPSG:32717"
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    modified_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "company": self.company,
            "crs": self.crs,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "modified_at": self.modified_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RSProjectMetadata":
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            author=d.get("author", ""),
            company=d.get("company", ""),
            crs=d.get("crs", "EPSG:32717"),
            tags=list(d.get("tags", [])),
            created_at=d.get("created_at", ""),
            modified_at=d.get("modified_at", ""),
        )


# =============================================================================
# RSProject — proyecto completo
# =============================================================================
@dataclass
class RSProject:
    metadata: RSProjectMetadata
    network: Network
    format_version: str = CURRENT_FORMAT_VERSION
    engine_version: str = ""

    # =========================================================================
    # Serialización
    # =========================================================================
    def to_dict(self) -> Dict[str, Any]:
        return {
            "format_version": self.format_version,
            "engine_version": self.engine_version,
            "metadata": self.metadata.to_dict(),
            "network": network_to_dict(self.network),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RSProject":
        fmt = d.get("format_version", "1.0")
        if fmt != CURRENT_FORMAT_VERSION:
            # Por ahora no hay migraciones. Solo soportamos 1.0.
            raise RSProjectError(
                f"Formato {fmt} no soportado. Esperaba {CURRENT_FORMAT_VERSION}."
            )

        try:
            net = dict_to_network(d["network"])
        except KeyError as e:
            raise RSProjectError(f"Falta campo {e} en el archivo")
        except (ValueError, TypeError) as e:
            raise RSProjectError(f"Error parseando red: {e}")

        return cls(
            metadata=RSProjectMetadata.from_dict(d.get("metadata", {})),
            network=net,
            format_version=fmt,
            engine_version=d.get("engine_version", ""),
        )

    # =========================================================================
    # Builder
    # =========================================================================
    @classmethod
    def from_network(
        cls,
        network: Network,
        author: str = "",
        company: str = "",
        description: str = "",
        crs: str = "EPSG:32717",
    ) -> "RSProject":
        """Construye un nuevo proyecto a partir de una Network."""
        from .. import __version__
        now = datetime.now().isoformat()
        return cls(
            metadata=RSProjectMetadata(
                name=network.name,
                description=description,
                author=author,
                company=company,
                crs=crs,
                created_at=now,
                modified_at=now,
            ),
            network=network,
            engine_version=__version__,
        )


# =============================================================================
# I/O helpers
# =============================================================================
def save_project(project: RSProject, path: str, indent: int = 2) -> str:
    """
    Guarda un RSProject como archivo .rsproj (JSON).

    Returns
    -------
    str : ruta absoluta al archivo guardado.
    """
    project.metadata.modified_at = datetime.now().isoformat()
    if not project.metadata.created_at:
        project.metadata.created_at = project.metadata.modified_at

    abs_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        json.dump(project.to_dict(), f, ensure_ascii=False, indent=indent)
    return abs_path


def load_project(path: str) -> RSProject:
    """Carga un .rsproj desde disco."""
    if not os.path.exists(path):
        raise RSProjectError(f"Archivo no encontrado: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise RSProjectError(f"No se pudo leer {path}: {e}")
    return RSProject.from_dict(data)
