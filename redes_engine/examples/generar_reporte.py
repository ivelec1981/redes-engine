# -*- coding: utf-8 -*-
"""
Pipeline completo: build → solve → analyze → reporte ejecutivo PDF + Word.

Demuestra el caso de uso "memoria técnica firmable" típico de SERCOP:
    1. Cargar red
    2. Resolver flujo de potencia
    3. Evaluar cumplimiento ARCERNNR
    4. Análisis 8760h con BESS dispatch peak shaving (G1)
    5. Análisis Host Capacity por bus
    6. Generar reporte PDF y Word listos para firma (G2)
"""

import os
import sys
from datetime import datetime

from ..core.compliance import ARCERNNR_EC, ComplianceAnalyzer
from ..hosting import HostingCapacityAnalyzer
from ..io.opendss_solver import OpenDSSSolver
from ..reports import ReportContext, generate_docx_report, generate_pdf_report
from ..timeseries import ProfileLibrary, TimeSeriesSolver
from .urbanizacion_mixta import build_urbanizacion_pastaza

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "reports_output")


def run() -> int:
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│  GENERACIÓN DE REPORTE EJECUTIVO (PDF + Word)               │")
    print("└─────────────────────────────────────────────────────────────┘\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 1. Construir red ──────────────────────────────────────────────
    print("📐 [1/5] Construyendo red...")
    net = build_urbanizacion_pastaza()
    print(f"     ✓ {len(net.buses)} buses, {len(net.branches)} branches")

    # ── 2. Resolver flujo ──────────────────────────────────────────────
    print("\n⚡ [2/5] Resolviendo flujo de potencia...")
    with OpenDSSSolver(net) as solver:
        solver.solve()
        flow = solver.collect_results()
    print(f"     ✓ Convergió en {flow.iterations} iter, "
          f"pérdidas {flow.losses_pct:.2f}%")

    # ── 3. Evaluar ARCERNNR ────────────────────────────────────────────
    print("\n🛡 [3/5] Evaluando ARCERNNR...")
    compliance = ComplianceAnalyzer(ARCERNNR_EC).analyze(flow)
    print(f"     ✓ {len(compliance.violations())} viol, "
          f"{len(compliance.warnings())} advert")

    # ── 4. Análisis 8760h con peak-shaving (G1) ───────────────────────
    print("\n⏱ [4/5] Análisis anual 168h con BESS peak-shaving...")
    profiles = ProfileLibrary.ecuador_default()
    ts = TimeSeriesSolver(net, profiles=profiles, dispatch_mode="peak_shaving")
    annual = ts.run(hours=168, scenario_name="Demo Reporte")
    print(f"     ✓ {annual.n_hours_simulated}h, trafo pico "
          f"{annual.peak_transformer_loading_pct:.1f}%")

    # ── 5. Host Capacity ──────────────────────────────────────────────
    print("\n🏠 [5/5] Análisis Host Capacity...")
    hosting = HostingCapacityAnalyzer(net).analyze_all(
        n_critical_hours=20, max_kw=200, tolerance_kw=10,
    )
    print(f"     ✓ {hosting.n_buses_analyzed} buses, "
          f"{hosting.elapsed_seconds:.1f}s")

    # ── 6. Construir contexto del reporte ─────────────────────────────
    print("\n📄 Generando reportes ejecutivos...")
    ctx = ReportContext(
        title="Análisis Integral de Red de Distribución",
        subtitle="Urbanización El Pastaza — Estudio técnico-eléctrico",
        project_name="El Pastaza Etapa 2",
        company_name="Empresa Eléctrica de Ejemplo S.A.",
        company_logo=None,   # poner ruta a PNG/JPG si existe
        author_name="Ing. Juan Pérez",
        author_id="SENESCYT 1234567890",
        author_email="juan.perez@empresa.ec",
        document_code="ER-2026-001",
        revision="01",
        issue_date=datetime.now(),
        network=net,
        flow_result=flow,
        compliance_report=compliance,
        annual_results=annual,
        hosting_results=hosting,
        include_charts=True,
        include_recommendations=True,
        extra_notes=(
            "Este reporte fue generado automáticamente por redes_engine v0.1.0. "
            "Verificación adicional requiere validación in-situ."
        ),
    )

    # ── PDF ──────────────────────────────────────────────────────────
    pdf_path = os.path.join(OUTPUT_DIR, "reporte_ejecutivo.pdf")
    generate_pdf_report(ctx, pdf_path)
    pdf_kb = os.path.getsize(pdf_path) / 1024
    print(f"     ✓ PDF: {pdf_path} ({pdf_kb:.1f} KB)")

    # ── Word ─────────────────────────────────────────────────────────
    docx_path = os.path.join(OUTPUT_DIR, "reporte_ejecutivo.docx")
    generate_docx_report(ctx, docx_path)
    docx_kb = os.path.getsize(docx_path) / 1024
    print(f"     ✓ Word: {docx_path} ({docx_kb:.1f} KB)")

    print("\n" + "═" * 65)
    print("  ✅ REPORTES GENERADOS Y LISTOS PARA FIRMA")
    print("═" * 65)
    print()
    print("  Contenido del reporte:")
    print("    • Portada con logo + datos del responsable")
    print("    • Resumen ejecutivo")
    print("    • Descripción de la red")
    print("    • Flujo de potencia + tablas + gráficos")
    print("    • Cumplimiento ARCERNNR Reg. 002/20")
    print("    • Análisis temporal 168h")
    print("    • Capacidad de alojamiento por bus")
    print("    • Recomendaciones automáticas")
    print()
    print("  Pie de página: código documento + revisión + fecha + página")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(run())
