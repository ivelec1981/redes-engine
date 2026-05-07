# -*- coding: utf-8 -*-
"""
redes_engine.persistence.container
====================================

Formato `.rsproj` multifile (contenedor ZIP).

Estructura del archivo (todas las entradas son texto UTF-8):

    <project>.rsproj  (ZIP)
    ├── manifest.json     — version + engine_version + created/modified
    ├── metadata.json     — autor, empresa, descripción, CRS, tags
    ├── network.json      — Network completo (mismo schema legacy)
    ├── calculos.json     — snapshot de resultados (PF, hosting, anual, compliance)
    ├── catalogo.json     — opcional: catálogo UC asociado al proyecto
    └── historial.log     — bitácora de operaciones (texto)

Compatibilidad
--------------
`load_project_any(path)` detecta automáticamente:
    1. Archivo ZIP (formato multifile v2)
    2. Archivo JSON plano (formato legacy v1) — se carga vía `persistence.project`

Esta detección permite migración transparente: un proyecto antiguo se abre,
se modifica y al guardarlo pasa al nuevo formato sin que el usuario haga nada.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from ..core.network import Network
from .project import (
    CURRENT_FORMAT_VERSION,
    RSProject,
    RSProjectError,
    RSProjectMetadata,
    load_project as load_legacy_project,
)
from .serialization import dict_to_network, network_to_dict


CONTAINER_FORMAT_VERSION = "2.0"

# Nombres de los archivos dentro del ZIP
_ENTRY_MANIFEST   = "manifest.json"
_ENTRY_METADATA   = "metadata.json"
_ENTRY_NETWORK    = "network.json"
_ENTRY_CALCULOS   = "calculos.json"
_ENTRY_CATALOGO   = "catalogo.json"
_ENTRY_HISTORIAL  = "historial.log"


# =============================================================================
# Estructura en memoria del contenedor
# =============================================================================
@dataclass
class RSProjectContainer:
    """
    Contenedor `.rsproj` v2.0 — agrupa Network + metadatos + resultados + log.

    El campo `network` es obligatorio; el resto son opcionales y pueden
    ser `None`/`{}` si el proyecto no los contiene.
    """
    network: Network
    metadata: RSProjectMetadata = field(default_factory=RSProjectMetadata)
    calculos: Dict[str, Any] = field(default_factory=dict)
    catalogo: Optional[Dict[str, Any]] = None
    historial: str = ""
    format_version: str = CONTAINER_FORMAT_VERSION
    engine_version: str = ""

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
        calculos: Optional[Dict[str, Any]] = None,
        catalogo: Optional[Dict[str, Any]] = None,
        historial: str = "",
    ) -> "RSProjectContainer":
        from .. import __version__
        now = datetime.now().isoformat()
        meta = RSProjectMetadata(
            name=network.name,
            description=description,
            author=author,
            company=company,
            crs=crs,
            created_at=now,
            modified_at=now,
        )
        return cls(
            network=network,
            metadata=meta,
            calculos=calculos or {},
            catalogo=catalogo,
            historial=historial,
            engine_version=__version__,
        )

    # =========================================================================
    # I/O
    # =========================================================================
    def write_zip_bytes(self, indent: int = 2) -> bytes:
        """Serializa el contenedor a bytes (ZIP en memoria)."""
        self.metadata.modified_at = datetime.now().isoformat()
        if not self.metadata.created_at:
            self.metadata.created_at = self.metadata.modified_at

        manifest = {
            "format_version": self.format_version,
            "engine_version": self.engine_version,
            "created_at": self.metadata.created_at,
            "modified_at": self.metadata.modified_at,
        }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                _ENTRY_MANIFEST,
                json.dumps(manifest, ensure_ascii=False, indent=indent),
            )
            zf.writestr(
                _ENTRY_METADATA,
                json.dumps(
                    self.metadata.to_dict(), ensure_ascii=False, indent=indent,
                ),
            )
            zf.writestr(
                _ENTRY_NETWORK,
                json.dumps(
                    network_to_dict(self.network),
                    ensure_ascii=False, indent=indent,
                ),
            )
            zf.writestr(
                _ENTRY_CALCULOS,
                json.dumps(self.calculos, ensure_ascii=False, indent=indent),
            )
            if self.catalogo is not None:
                zf.writestr(
                    _ENTRY_CATALOGO,
                    json.dumps(self.catalogo, ensure_ascii=False, indent=indent),
                )
            zf.writestr(_ENTRY_HISTORIAL, self.historial or "")

        return buf.getvalue()

    def save(self, path: str, indent: int = 2) -> str:
        """Guarda el contenedor a disco como archivo ZIP."""
        abs_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(self.write_zip_bytes(indent=indent))
        return abs_path

    @classmethod
    def from_zip_bytes(cls, data: bytes) -> "RSProjectContainer":
        """Carga un contenedor desde bytes."""
        try:
            with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
                names = set(zf.namelist())
                if _ENTRY_NETWORK not in names:
                    raise RSProjectError(
                        f"Archivo .rsproj inválido: falta {_ENTRY_NETWORK}"
                    )

                manifest = _read_json(zf, _ENTRY_MANIFEST, default={})
                meta_dict = _read_json(zf, _ENTRY_METADATA, default={})
                net_dict = _read_json(zf, _ENTRY_NETWORK, default=None)
                calc_dict = _read_json(zf, _ENTRY_CALCULOS, default={})
                cat_dict = (
                    _read_json(zf, _ENTRY_CATALOGO, default=None)
                    if _ENTRY_CATALOGO in names else None
                )
                historial = (
                    zf.read(_ENTRY_HISTORIAL).decode("utf-8", errors="replace")
                    if _ENTRY_HISTORIAL in names else ""
                )
        except zipfile.BadZipFile:
            raise RSProjectError("Archivo .rsproj corrupto: ZIP inválido")

        if net_dict is None:
            raise RSProjectError(f"{_ENTRY_NETWORK} vacío o ilegible")

        try:
            net = dict_to_network(net_dict)
        except (KeyError, ValueError, TypeError) as e:
            raise RSProjectError(f"No se pudo deserializar la red: {e}")

        meta = RSProjectMetadata.from_dict(meta_dict or {})

        return cls(
            network=net,
            metadata=meta,
            calculos=calc_dict or {},
            catalogo=cat_dict,
            historial=historial,
            format_version=manifest.get("format_version", CONTAINER_FORMAT_VERSION),
            engine_version=manifest.get("engine_version", ""),
        )

    @classmethod
    def load(cls, path: str) -> "RSProjectContainer":
        """Carga un contenedor desde disco."""
        if not os.path.exists(path):
            raise RSProjectError(f"Archivo no encontrado: {path}")
        with open(path, "rb") as f:
            return cls.from_zip_bytes(f.read())

    # =========================================================================
    # Conversión a/desde el formato legacy `RSProject`
    # =========================================================================
    def to_legacy_project(self) -> RSProject:
        """Crea un `RSProject` (formato 1.0) ignorando los extras."""
        return RSProject(
            metadata=self.metadata,
            network=self.network,
            engine_version=self.engine_version,
        )

    @classmethod
    def from_legacy_project(cls, project: RSProject) -> "RSProjectContainer":
        return cls(
            network=project.network,
            metadata=project.metadata,
            engine_version=project.engine_version,
        )


# =============================================================================
# Helpers
# =============================================================================
def _read_json(zf: zipfile.ZipFile, name: str, default: Any = None) -> Any:
    """Lee y parsea un JSON dentro del ZIP. Devuelve `default` si no existe."""
    try:
        raw = zf.read(name)
    except KeyError:
        return default
    if not raw:
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise RSProjectError(f"Entrada {name} ilegible: {e}")


def _looks_like_zip(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        return head[:2] == b"PK"
    except OSError:
        return False


# =============================================================================
# API pública del contenedor (con detección automática)
# =============================================================================
def save_container(container: RSProjectContainer, path: str, indent: int = 2) -> str:
    """Guarda un contenedor como `.rsproj` v2.0 (ZIP)."""
    return container.save(path, indent=indent)


def load_container(path: str) -> RSProjectContainer:
    """
    Carga un `.rsproj` desde disco. Detecta automáticamente:
        - ZIP container v2.0  → RSProjectContainer
        - JSON plano legacy v1 → RSProjectContainer (extras vacíos)

    Retorna siempre un `RSProjectContainer` para que el resto de la app
    pueda trabajar con un único tipo.
    """
    if not os.path.exists(path):
        raise RSProjectError(f"Archivo no encontrado: {path}")

    if _looks_like_zip(path):
        return RSProjectContainer.load(path)

    # Fallback: formato legacy 1.0 (JSON plano)
    legacy = load_legacy_project(path)
    return RSProjectContainer.from_legacy_project(legacy)


def load_container_from_bytes(data: bytes) -> RSProjectContainer:
    """Igual que `load_container` pero desde bytes (e.g. upload HTTP)."""
    if data[:2] == b"PK":
        return RSProjectContainer.from_zip_bytes(data)
    # JSON plano legacy
    try:
        d = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise RSProjectError(f"No es un .rsproj válido: {e}")
    legacy = RSProject.from_dict(d)
    return RSProjectContainer.from_legacy_project(legacy)
