# -*- coding: utf-8 -*-
"""
redes_engine.persistence
=========================

Serialización completa de Network → archivo `.rsproj` (JSON).

Permite:
    - Guardar el estado completo de un proyecto
    - Compartir entre usuarios y máquinas
    - Versionar (Git) — el .rsproj es texto JSON legible
    - Cargar un proyecto previo y continuar el análisis
"""

from .container import (
    CONTAINER_FORMAT_VERSION,
    RSProjectContainer,
    load_container,
    load_container_from_bytes,
    save_container,
)
from .project import (
    RSProject,
    RSProjectError,
    RSProjectMetadata,
    load_project,
    save_project,
)
from .results_io import stored_results_to_dict
from .serialization import dict_to_network, network_to_dict

__all__ = [
    "RSProject", "RSProjectMetadata", "RSProjectError",
    "save_project", "load_project",
    "network_to_dict", "dict_to_network",
    # Multifile container v2.0
    "RSProjectContainer", "CONTAINER_FORMAT_VERSION",
    "save_container", "load_container", "load_container_from_bytes",
    "stored_results_to_dict",
]
