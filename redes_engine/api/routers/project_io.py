# -*- coding: utf-8 -*-
"""
redes_engine.api.routers.project_io
======================================

Endpoints para guardar/cargar proyectos `.rsproj`.

Formato actual: contenedor ZIP multifile v2.0
    manifest.json + metadata.json + network.json +
    calculos.json + catalogo.json (opc.) + historial.log

Formato legacy: JSON plano v1.0 (se sigue aceptando en `/load`).
"""

import os
import shutil
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from ...persistence import (
    RSProjectContainer,
    RSProjectError,
    load_container_from_bytes,
    stored_results_to_dict,
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
    Serializa la red al contenedor `.rsproj` v2.0 (ZIP) y devuelve descarga.

    El contenedor incluye:
        - network.json    (Network completo)
        - calculos.json   (snapshot de PF, hosting, anual, compliance)
        - metadata.json   (autor, empresa, descripción)
        - historial.log   (bitácora del proyecto)
    """
    stored = get_store().get(network_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Network not found")

    # Snapshot de resultados + estado de workflow (dominios/docs) para que
    # al recargar no se pierda el progreso lossless del workflow.
    calculos = stored_results_to_dict(stored)
    calculos["workflow"] = {
        "active_domains": list(stored.active_domains),
        "emitted_docs": list(stored.emitted_docs),
    }

    container = RSProjectContainer.from_network(
        stored.network,
        author=opts.author,
        company=opts.company,
        description=opts.description,
        crs=stored.crs,
        calculos=calculos,
        historial=_render_default_historial(stored),
    )

    tmpdir = tempfile.mkdtemp(prefix="rsproj_")
    safe_name = "".join(
        c for c in stored.name if c.isalnum() or c in "._- "
    ).strip() or "project"
    path = os.path.join(tmpdir, f"{safe_name}.rsproj")
    container.save(path)

    # Track emisión para el workflow (atómico bajo el lock del store)
    get_store().add_emitted_doc(network_id, "rsproj")

    return FileResponse(
        path,
        media_type="application/zip",
        filename=os.path.basename(path),
        # Borrar el tempdir tras enviar la respuesta (evita fuga de disco).
        background=BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True),
    )


# =============================================================================
# POST /projects/load  — subir .rsproj (v1 o v2) y crear network
# =============================================================================
@router.post("/load", response_model=NetworkSummaryOut, status_code=201)
async def load_rsproj_file(file: UploadFile = File(...)):
    """
    Acepta upload de un archivo `.rsproj` (cualquier versión) y crea un
    Network nuevo en el store. Detecta automáticamente:
        - v2.0 ZIP container
        - v1.0 JSON plano (legacy)
    """
    if not file.filename or not (
        file.filename.endswith(".rsproj") or file.filename.endswith(".json")
    ):
        raise HTTPException(
            status_code=400,
            detail="Se esperaba archivo .rsproj o .json",
        )

    try:
        content = await file.read()
        container = load_container_from_bytes(content)
    except RSProjectError as e:
        raise HTTPException(status_code=400, detail=f"Proyecto inválido: {e}")

    store = get_store()
    stored = store.create(
        name=container.network.name,
        network=container.network,
        crs=container.metadata.crs,
    )
    # Restaurar estado de workflow lossless (dominios activos y docs emitidos)
    # que se persistió en el contenedor; los resultados de cálculo en
    # calculos.json son un snapshot resumen y quedan disponibles en
    # stored.loaded_calculos para inspección/reportes.
    if container.calculos:
        stored.loaded_calculos = container.calculos
        wf = container.calculos.get("workflow") if isinstance(
            container.calculos, dict
        ) else None
        if isinstance(wf, dict):
            stored.active_domains = list(wf.get("active_domains", []))
            stored.emitted_docs = list(wf.get("emitted_docs", []))
    return _to_summary(stored)


# =============================================================================
# Helpers internos
# =============================================================================
def _render_default_historial(stored) -> str:
    """Genera una bitácora textual con el estado actual del proyecto."""
    lines = [
        f"# Historial proyecto {stored.name}",
        f"network_id: {stored.id}",
        f"crs: {stored.crs}",
    ]
    net = stored.network
    lines.append(
        f"buses={len(net.buses)} branches={len(net.branches)} "
        f"assets={len(net.assets)}"
    )
    if stored.last_solve_result is not None:
        r = stored.last_solve_result
        lines.append(
            f"power_flow: convergido={r.converged} "
            f"perdidas={r.losses_pct:.2f}%"
        )
    if stored.last_compliance_report is not None:
        c = stored.last_compliance_report
        lines.append(
            f"compliance: {c.overall_status.value} "
            f"violations={len(c.violations())} "
            f"warnings={len(c.warnings())}"
        )
    if stored.last_hosting_results is not None:
        h = stored.last_hosting_results
        lines.append(f"hosting: {h.n_buses_analyzed} buses analizados")
    if stored.last_annual_results is not None:
        a = stored.last_annual_results
        lines.append(f"annual: {a.n_hours_simulated} horas simuladas")
    if stored.active_domains:
        lines.append("dominios_activos: " + ", ".join(stored.active_domains))
    if stored.emitted_docs:
        lines.append("documentos_emitidos: " + ", ".join(stored.emitted_docs))
    return "\n".join(lines) + "\n"
