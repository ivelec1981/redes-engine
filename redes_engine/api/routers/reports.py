# -*- coding: utf-8 -*-
"""
redes_engine.api.routers.reports
==================================

Endpoint que genera reporte ejecutivo PDF/Word descargable.
"""

import os
import shutil
import tempfile
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from ...reports import (
    ReportContext,
    generate_docx_report,
    generate_pdf_report,
)
from ..storage import StoredNetwork, get_store

router = APIRouter(prefix="/api/v1/networks", tags=["reports"])


# =============================================================================
# Schema de entrada
# =============================================================================
class ReportRequest(BaseModel):
    format: Literal["pdf", "docx"] = "pdf"
    title: str = "Análisis Integral de Red de Distribución"
    subtitle: str = "Reporte técnico-eléctrico"
    project_name: str = ""
    company_name: str = "Empresa Eléctrica"
    author_name: str = "Ing. Responsable"
    author_id: Optional[str] = None
    author_email: Optional[str] = None
    document_code: Optional[str] = None
    revision: str = "01"
    include_charts: bool = True
    include_recommendations: bool = True
    extra_notes: Optional[str] = None


def _get_or_404(network_id: str) -> StoredNetwork:
    stored = get_store().get(network_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return stored


# =============================================================================
# POST /networks/{id}/report  — generar PDF o DOCX
# =============================================================================
@router.post("/{network_id}/report")
def generate_report(network_id: str, req: ReportRequest):
    """
    Genera un reporte ejecutivo del análisis y lo devuelve como descarga.

    Requiere que se hayan ejecutado previamente:
        - POST /networks/{id}/solve   (para tener flow_result)

    Opcionalmente incluye los resultados de:
        - POST /networks/{id}/timeseries
        - POST /networks/{id}/hosting

    Si no hay solve previo, retorna 400.
    """
    stored = _get_or_404(network_id)

    if stored.last_solve_result is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "No hay resultados de flujo de potencia. "
                "Ejecute primero POST /networks/{id}/solve"
            ),
        )

    # Construir contexto
    ctx = ReportContext(
        title=req.title,
        subtitle=req.subtitle,
        project_name=req.project_name or stored.name,
        company_name=req.company_name,
        author_name=req.author_name,
        author_id=req.author_id or "",
        author_email=req.author_email or "",
        document_code=req.document_code or f"RE-{stored.id[:8]}",
        revision=req.revision,
        issue_date=datetime.now(),
        network=stored.network,
        flow_result=stored.last_solve_result,
        compliance_report=stored.last_compliance_report,
        annual_results=stored.last_annual_results,
        hosting_results=stored.last_hosting_results,
        include_charts=req.include_charts,
        include_recommendations=req.include_recommendations,
        extra_notes=req.extra_notes or "",
    )

    # Generar archivo en tempdir
    tmpdir = tempfile.mkdtemp(prefix="report_")
    if req.format == "pdf":
        path = os.path.join(tmpdir, f"{stored.name}_reporte.pdf")
        generate_pdf_report(ctx, path)
        media_type = "application/pdf"
        get_store().add_emitted_doc(stored.id, "pdf")
    else:
        path = os.path.join(tmpdir, f"{stored.name}_reporte.docx")
        generate_docx_report(ctx, path)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        get_store().add_emitted_doc(stored.id, "docx")

    return FileResponse(
        path,
        media_type=media_type,
        filename=os.path.basename(path),
        # Borrar el tempdir tras enviar la respuesta (evita fuga de disco).
        background=BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True),
    )
