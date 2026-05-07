# -*- coding: utf-8 -*-
"""
redes_engine.reports.executive_pdf
====================================

Generador de reporte ejecutivo en PDF usando ReportLab.

Diseño:
    - Portada con logo, título, datos del responsable
    - Resumen ejecutivo
    - Secciones técnicas con tablas y figuras
    - Pie de página con número de página y código de documento
"""

import io
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import charts
from .builder import ReportBuilder, ReportContext, ReportSection


# =============================================================================
# Estilos
# =============================================================================
def _build_styles():
    base = getSampleStyleSheet()
    # Personalizar
    base.add(ParagraphStyle(
        name="MyTitle",
        parent=base["Title"],
        fontSize=22, leading=26,
        textColor=colors.HexColor("#1a237e"),
        alignment=1, spaceAfter=14,
    ))
    base.add(ParagraphStyle(
        name="MySubtitle",
        parent=base["Heading2"],
        fontSize=13, leading=16,
        textColor=colors.HexColor("#5a6373"),
        alignment=1, spaceAfter=10,
    ))
    base.add(ParagraphStyle(
        name="MyHeading",
        parent=base["Heading2"],
        fontSize=14, leading=18,
        textColor=colors.HexColor("#1a237e"),
        spaceBefore=14, spaceAfter=8,
    ))
    base.add(ParagraphStyle(
        name="MyBody",
        parent=base["BodyText"],
        fontSize=10, leading=14,
        textColor=colors.HexColor("#212121"),
        alignment=4, spaceAfter=6,
    ))
    base.add(ParagraphStyle(
        name="MyFooter",
        parent=base["Normal"],
        fontSize=8, leading=10,
        textColor=colors.HexColor("#9e9e9e"),
        alignment=1,
    ))
    return base


# =============================================================================
# Cabecera/pie en cada página
# =============================================================================
def _make_page_decorator(ctx: ReportContext):
    def on_page(canvas_obj, doc):
        canvas_obj.saveState()
        # Pie de página
        canvas_obj.setFont("Helvetica", 8)
        canvas_obj.setFillColor(colors.HexColor("#9e9e9e"))
        page_text = (
            f"{ctx.document_code or 'redes_engine'}  ·  "
            f"Rev. {ctx.revision}  ·  "
            f"{ctx.issue_date.strftime('%Y-%m-%d')}  ·  "
            f"Página {doc.page}"
        )
        canvas_obj.drawCentredString(A4[0] / 2, 1.2 * cm, page_text)

        # Línea decorativa superior
        canvas_obj.setStrokeColor(colors.HexColor("#1a237e"))
        canvas_obj.setLineWidth(0.8)
        canvas_obj.line(2 * cm, A4[1] - 1.5 * cm,
                         A4[0] - 2 * cm, A4[1] - 1.5 * cm)

        canvas_obj.restoreState()
    return on_page


# =============================================================================
# Portada
# =============================================================================
def _build_cover(ctx: ReportContext, styles) -> list:
    elems = []
    elems.append(Spacer(1, 4 * cm))

    if ctx.company_logo:
        try:
            elems.append(Image(ctx.company_logo, width=4 * cm, height=4 * cm))
        except Exception:
            pass

    elems.append(Paragraph(ctx.title, styles["MyTitle"]))
    elems.append(Paragraph(ctx.subtitle, styles["MySubtitle"]))
    elems.append(Spacer(1, 2 * cm))

    cover_table = Table([
        ["Proyecto", ctx.project_name or "—"],
        ["Empresa", ctx.company_name],
        ["Responsable", ctx.author_name],
        ["Licencia", ctx.author_id or "—"],
        ["Email", ctx.author_email or "—"],
        ["Código documento", ctx.document_code or "—"],
        ["Revisión", ctx.revision],
        ["Fecha de emisión", ctx.issue_date.strftime("%d/%m/%Y")],
    ], colWidths=[5 * cm, 9 * cm])
    cover_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E3F2FD")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1a237e")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#BDBDBD")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elems.append(cover_table)

    elems.append(Spacer(1, 4 * cm))
    elems.append(Paragraph(
        "Generado por <b>redes_engine</b> · Análisis alineado con "
        "ARCERNNR Reg. 002/20",
        styles["MyFooter"],
    ))
    elems.append(PageBreak())
    return elems


# =============================================================================
# Sección genérica
# =============================================================================
def _render_section(sec: ReportSection, styles, ctx: ReportContext) -> list:
    elems = []
    elems.append(Paragraph(sec.title, styles["MyHeading"]))
    for para in sec.body_paragraphs:
        elems.append(Paragraph(para, styles["MyBody"]))
        elems.append(Spacer(1, 4))

    for tbl in sec.tables:
        if tbl.get("title"):
            elems.append(Spacer(1, 6))
            elems.append(Paragraph(
                f"<b>{tbl['title']}</b>", styles["MyBody"]
            ))
        data = [tbl["headers"]] + [list(map(str, row)) for row in tbl["rows"]]
        col_count = len(tbl["headers"])
        # Anchos proporcionales
        page_width = A4[0] - 4 * cm
        col_widths = [page_width / col_count] * col_count

        rl_tbl = Table(data, colWidths=col_widths, repeatRows=1)
        rl_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F5F7FA")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#BDBDBD")),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elems.append(rl_tbl)
        elems.append(Spacer(1, 8))

    return elems


# =============================================================================
# Charts embebidos
# =============================================================================
def _add_charts_for_section(sec_title: str, ctx: ReportContext) -> list:
    """Devuelve elementos Image con las figuras matplotlib correspondientes."""
    elems = []
    if not ctx.include_charts:
        return elems

    if "Flujo de Potencia" in sec_title and ctx.has_solve:
        try:
            png1 = charts.bar_voltage_profile(ctx.flow_result)
            png2 = charts.bar_branch_loading(ctx.flow_result)
            elems.append(Spacer(1, 8))
            elems.append(Image(io.BytesIO(png1),
                                width=16*cm, height=8.4*cm))
            elems.append(Spacer(1, 6))
            elems.append(Image(io.BytesIO(png2),
                                width=16*cm, height=8.4*cm))
        except Exception:
            pass
    elif "Capacidad de Alojamiento" in sec_title and ctx.has_hosting:
        try:
            png = charts.hosting_capacity_chart(ctx.hosting_results)
            elems.append(Spacer(1, 8))
            elems.append(Image(io.BytesIO(png),
                                width=16*cm, height=9*cm))
        except Exception:
            pass
    return elems


# =============================================================================
# ENTRADA PÚBLICA
# =============================================================================
def generate_pdf_report(
    context: ReportContext,
    output_path: str,
) -> str:
    """
    Genera un reporte PDF con todas las secciones disponibles.

    Returns
    -------
    str : ruta al PDF generado.
    """
    styles = _build_styles()
    builder = ReportBuilder(context)
    sections = builder.build_all()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2.2 * cm, bottomMargin=2 * cm,
        title=context.title,
        author=context.author_name,
    )
    story = []

    # Portada
    story.extend(_build_cover(context, styles))

    # Secciones
    for sec in sections:
        story.extend(_render_section(sec, styles, context))
        story.extend(_add_charts_for_section(sec.title, context))
        story.append(Spacer(1, 6))

    # Notas finales
    if context.extra_notes:
        story.append(Paragraph(
            "<b>Notas adicionales</b>", styles["MyHeading"]
        ))
        story.append(Paragraph(context.extra_notes, styles["MyBody"]))

    decorator = _make_page_decorator(context)
    doc.build(story, onFirstPage=decorator, onLaterPages=decorator)
    return output_path
