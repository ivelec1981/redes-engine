# -*- coding: utf-8 -*-
"""
redes_engine.reports
=====================

Generación de reportes ejecutivos firmables (PDF y Word).

Toma:
    - Network
    - PowerFlowResult
    - ComplianceReport (opcional)
    - HostingCapacityResults (opcional)
    - AnnualResults (opcional)

Y genera:
    - PDF (ReportLab) — para firma digital y entrega SERCOP
    - Word (.docx) — para edición posterior y cliente final
    - Charts matplotlib embebidos (perfiles, ranking, mapa de calor)
"""

from .builder import (
    ReportBuilder,
    ReportContext,
    ReportSection,
)
from .executive_docx import generate_docx_report
from .executive_pdf import generate_pdf_report

__all__ = [
    "ReportBuilder", "ReportContext", "ReportSection",
    "generate_pdf_report", "generate_docx_report",
]
