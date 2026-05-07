# -*- coding: utf-8 -*-
"""
redes_engine.api.routers.project_io
======================================

Endpoints para guardar/cargar proyectos `.rsproj`.
"""

import json
import os
import tempfile
from typing import Any, Dict

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...persistence import (
    RSProject,
    RSProjectError,
    load_project,
    save_project,
)
from ..routers.networks import _to_summary
from ..schemas.network import NetworkSummaryOut
from ..storage import get_store

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


# =============================================================================
# POST /projects/save/{network_id}  — descargar como .rsproj
# =============================================================================
class SaveOptions(BaseModel):
    author: str = ""
    company: str = ""
    description: str = ""


@router.post("/save/{network_id}")
def save_network_as_rsproj(network_id: str, opts: SaveOptions = SaveOptions()):
    """
    Serializa la red al formato `.rsproj` y devuelve descarga del archivo.
    """
    stored = get_store().get(network_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Network not found")

    project = RSProject.from_network(
        stored.network,
        author=opts.author,
        company=opts.company,
        description=opts.description,
        crs=stored.crs,
    )

    tmpdir = tempfile.mkdtemp(prefix="rsproj_")
    safe_name = "".join(
        c for c in stored.name if c.isalnum() or c in "._- "
    ).strip() or "project"
    path = os.path.join(tmpdir, f"{safe_name}.rsproj")
    save_project(project, path)

    return FileResponse(
        path,
        media_type="application/json",
        filename=os.path.basename(path),
    )


# =============================================================================
# POST /projects/load  — subir .rsproj y crear network
# =============================================================================
@router.post("/load", response_model=NetworkSummaryOut, status_code=201)
async def load_rsproj_file(file: UploadFile = File(...)):
    """
    Acepta upload de un archivo `.rsproj` y crea un Network nuevo en el store.
    """
    if not file.filename.endswith(".rsproj") and not file.filename.endswith(".json"):
        raise HTTPException(
            status_code=400,
            detail="Se esperaba archivo .rsproj o .json",
        )

    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        project = RSProject.from_dict(data)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"JSON inválido: {e}")
    except RSProjectError as e:
        raise HTTPException(status_code=400, detail=f"Proyecto inválido: {e}")

    store = get_store()
    stored = store.create(
        name=project.network.name,
        network=project.network,
        crs=project.metadata.crs,
    )
    return _to_summary(stored)
