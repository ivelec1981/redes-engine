# -*- coding: utf-8 -*-
"""
redes_engine.reports.builder
=============================

Estructuras comunes para construir el contexto de un reporte ejecutivo.
Independiente del formato de salida (PDF/Word).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# =============================================================================
# Contexto: todos los datos necesarios para construir el reporte
# =============================================================================
@dataclass
class ReportContext:
    """
    Contiene todos los datos para el reporte ejecutivo.

    Atributos del flujo de potencia, compliance, etc. son opcionales —
    solo se incluyen las secciones para los datos disponibles.
    """
    title: str = "Reporte Técnico — redes_engine"
    subtitle: str = "Análisis Integral de Red de Distribución"
    project_name: str = ""
    company_name: str = "Empresa Eléctrica"
    company_logo: Optional[str] = None        # ruta a imagen del logo
    author_name: str = "Ing. Responsable"
    author_id: str = ""                       # No. de licencia profesional
    author_email: str = ""
    issue_date: datetime = field(default_factory=datetime.now)
    document_code: str = ""                   # ej: "ER-2026-001"
    revision: str = "01"

    # Objetos del motor (todos opcionales)
    network: Any = None
    flow_result: Any = None
    compliance_report: Any = None
    hosting_results: Any = None
    annual_results: Any = None

    # Personalización
    include_charts: bool = True
    include_recommendations: bool = True
    extra_notes: str = ""

    @property
    def has_solve(self) -> bool:
        return self.flow_result is not None

    @property
    def has_compliance(self) -> bool:
        return self.compliance_report is not None

    @property
    def has_hosting(self) -> bool:
        return self.hosting_results is not None

    @property
    def has_annual(self) -> bool:
        return self.annual_results is not None


# =============================================================================
# Sección genérica
# =============================================================================
@dataclass
class ReportSection:
    """Una sección del reporte (renderizada como capítulo)."""
    title: str
    body_paragraphs: List[str] = field(default_factory=list)
    tables: List[Dict[str, Any]] = field(default_factory=list)
    charts: List[Dict[str, Any]] = field(default_factory=list)


# =============================================================================
# Builder — construye las secciones desde el contexto
# =============================================================================
class ReportBuilder:
    """
    Construye una lista de ReportSection a partir del contexto.

    Cada generador (PDF/Word) consume estas secciones genéricas
    y las renderiza en su formato.
    """

    def __init__(self, context: ReportContext):
        self.ctx = context

    def build_all(self) -> List[ReportSection]:
        sections: List[ReportSection] = []
        sections.append(self._build_summary())
        if self.ctx.network:
            sections.append(self._build_network_description())
        if self.ctx.has_solve:
            sections.append(self._build_solve_section())
        if self.ctx.has_compliance:
            sections.append(self._build_compliance_section())
        if self.ctx.has_annual:
            sections.append(self._build_annual_section())
        if self.ctx.has_hosting:
            sections.append(self._build_hosting_section())
        if self.ctx.include_recommendations:
            sections.append(self._build_recommendations_section())
        return sections

    # =========================================================================
    # Sección: Resumen ejecutivo
    # =========================================================================
    def _build_summary(self) -> ReportSection:
        sec = ReportSection(title="Resumen Ejecutivo")

        intro = (
            f"Este reporte presenta el análisis integral de la red de "
            f"distribución eléctrica '{self.ctx.project_name}' realizado el "
            f"{self.ctx.issue_date.strftime('%d/%m/%Y')}. "
            f"El análisis se ejecutó con el motor redes_engine, una "
            f"plataforma open-source para diseño y operación de redes "
            f"alineada con la normativa ARCERNNR Reg. 002/20."
        )
        sec.body_paragraphs.append(intro)

        if self.ctx.network:
            n = self.ctx.network
            stats = (
                f"La red analizada cuenta con {len(n.buses)} buses "
                f"({sum(1 for b in n.buses.values() if b.is_mt())} MT y "
                f"{sum(1 for b in n.buses.values() if b.is_bt())} BT), "
                f"{len(n.branches)} elementos de transferencia "
                f"({len(n.lines())} líneas y {len(n.transformers())} "
                f"transformadores) y {len(n.assets)} activos conectados "
                f"(cargas, vehículos eléctricos, generación distribuida y "
                f"sistemas de almacenamiento). La demanda nominal total es "
                f"de {n.total_load_kw():.2f} kW."
            )
            sec.body_paragraphs.append(stats)

        if self.ctx.has_compliance:
            from ..core.results import ComplianceStatus
            cr = self.ctx.compliance_report
            n_viol = len(cr.violations())
            n_warn = len(cr.warnings())
            if cr.overall_status == ComplianceStatus.OK:
                veredict = (
                    "✓ La red CUMPLE plenamente la normativa ARCERNNR. "
                    "No se detectaron violaciones ni advertencias."
                )
            elif cr.overall_status == ComplianceStatus.WARNING:
                veredict = (
                    f"⚠ La red cumple normativa, pero presenta {n_warn} "
                    f"advertencia(s) que conviene monitorear."
                )
            else:
                veredict = (
                    f"✗ La red NO cumple normativa: se detectaron "
                    f"{n_viol} violación(es) que requieren intervención."
                )
            sec.body_paragraphs.append(veredict)

        return sec

    # =========================================================================
    # Sección: Descripción de la red
    # =========================================================================
    def _build_network_description(self) -> ReportSection:
        n = self.ctx.network
        sec = ReportSection(title="1. Descripción de la Red")
        sec.body_paragraphs.append(
            "Topología y elementos modelados:"
        )
        # Tabla resumen
        sec.tables.append({
            "title": "Inventario de elementos",
            "headers": ["Categoría", "Cantidad"],
            "rows": [
                ["Buses MT", sum(1 for b in n.buses.values() if b.is_mt())],
                ["Buses BT", sum(1 for b in n.buses.values() if b.is_bt())],
                ["Líneas aéreas y subterráneas", len(n.lines())],
                ["Transformadores", len(n.transformers())],
                ["Cargas residenciales/comerciales",
                 sum(1 for a in n.assets.values() if a.is_load())],
                ["Cargadores VE",
                 sum(1 for a in n.assets.values() if a.is_ev())],
                ["Sistemas PV",
                 sum(1 for a in n.assets.values() if a.is_pv())],
                ["BESS (almacenamiento)",
                 sum(1 for a in n.assets.values() if a.is_storage())],
            ],
        })
        return sec

    # =========================================================================
    # Sección: Flujo de potencia
    # =========================================================================
    def _build_solve_section(self) -> ReportSection:
        r = self.ctx.flow_result
        sec = ReportSection(title="2. Flujo de Potencia (OpenDSS)")
        sec.body_paragraphs.append(
            f"Se ejecutó un análisis de flujo de potencia con el motor "
            f"OpenDSS (EPRI). El solver convergió en {r.iterations} "
            f"iteraciones."
        )
        sec.tables.append({
            "title": "Métricas globales",
            "headers": ["Métrica", "Valor"],
            "rows": [
                ["Potencia activa total", f"{r.total_power_kw:.2f} kW"],
                ["Potencia reactiva total", f"{r.total_power_kvar:.2f} kvar"],
                ["Pérdidas activas", f"{r.total_losses_kw:.3f} kW"],
                ["Pérdidas como % de la demanda", f"{r.losses_pct:.2f}%"],
                ["Buses analizados", len(r.bus_voltages)],
                ["Branches analizados", len(r.branch_flows)],
            ],
        })

        # Worst voltage / worst branch
        worst_v = r.worst_voltage()
        worst_b = r.worst_loaded_branch()
        if worst_v:
            sec.body_paragraphs.append(
                f"La peor caída de voltaje ocurre en el bus {worst_v.bus_id} "
                f"con ΔV = {worst_v.v_drop_pct:+.2f}% "
                f"({worst_v.compliance.value})."
            )
        if worst_b:
            sec.body_paragraphs.append(
                f"El elemento más cargado es {worst_b.branch_id} "
                f"con utilización del {worst_b.loading_pct:.1f}%."
            )

        # Tabla detallada de buses
        sec.tables.append({
            "title": "Voltajes por bus",
            "headers": ["Bus", "Vnom (kV)", "V (pu)", "ΔV%", "Estado"],
            "rows": [
                [v.bus_id, f"{v.voltage_nominal_kv:.3f}",
                 f"{v.v_pu:.4f}", f"{v.v_drop_pct:+.2f}%",
                 v.compliance.value]
                for v in r.bus_voltages.values()
            ],
        })
        return sec

    # =========================================================================
    # Sección: Compliance ARCERNNR
    # =========================================================================
    def _build_compliance_section(self) -> ReportSection:
        cr = self.ctx.compliance_report
        sec = ReportSection(
            title="3. Cumplimiento Normativo (ARCERNNR Reg. 002/20)"
        )
        sec.body_paragraphs.append(
            f"Marco normativo aplicado: {cr.framework.value}. "
            f"El motor evaluó {len(cr.findings)} parámetros: "
            f"{len(cr.passed())} cumplen, {len(cr.warnings())} en advertencia, "
            f"{len(cr.violations())} violaciones."
        )
        if cr.violations():
            sec.tables.append({
                "title": "Violaciones detectadas",
                "headers": ["Categoría", "Elemento", "Mensaje"],
                "rows": [
                    [v.category, v.element_id, v.message]
                    for v in cr.violations()
                ],
            })
        if cr.warnings():
            sec.tables.append({
                "title": "Advertencias (a monitorear)",
                "headers": ["Categoría", "Elemento", "Mensaje"],
                "rows": [
                    [w.category, w.element_id, w.message]
                    for w in cr.warnings()
                ],
            })
        return sec

    # =========================================================================
    # Sección: Análisis 8760h
    # =========================================================================
    def _build_annual_section(self) -> ReportSection:
        ar = self.ctx.annual_results
        sec = ReportSection(title="4. Análisis Temporal Anual (8760h)")
        sec.body_paragraphs.append(
            f"Se simularon {ar.n_hours_simulated} horas con perfiles "
            f"realistas para cargas residenciales/comerciales, generación "
            f"PV y carga de vehículos eléctricos. Escenario: "
            f"'{ar.scenario_name}'."
        )
        sec.tables.append({
            "title": "Métricas anuales",
            "headers": ["Métrica", "Valor"],
            "rows": [
                ["Energía servida",
                 f"{ar.total_energy_served_mwh:.2f} MWh"],
                ["Energía importada",
                 f"{ar.total_energy_imported_mwh:.2f} MWh"],
                ["Energía exportada (PV→red)",
                 f"{ar.total_energy_exported_mwh:.2f} MWh"],
                ["Pérdidas técnicas",
                 f"{ar.total_losses_mwh:.2f} MWh ({ar.losses_pct:.2f}%)"],
                ["Demanda pico",
                 f"{ar.peak_demand_kw:.2f} kW (h={ar.peak_demand_hour})"],
                ["Demanda promedio", f"{ar.avg_demand_kw:.2f} kW"],
                ["Factor de carga", f"{ar.load_factor:.3f}"],
                ["Buses con violación (≥1h)",
                 len(ar.buses_with_violation_hours)],
                ["Branches sobrecargados",
                 len(ar.branches_with_overload_hours)],
            ],
        })

        if ar.peak_transformer_id:
            sec.body_paragraphs.append(
                f"El transformador más cargado en el año es "
                f"{ar.peak_transformer_id} con utilización pico de "
                f"{ar.peak_transformer_loading_pct:.1f}%."
            )
        return sec

    # =========================================================================
    # Sección: Host Capacity
    # =========================================================================
    def _build_hosting_section(self) -> ReportSection:
        hr = self.ctx.hosting_results
        sec = ReportSection(title="5. Capacidad de Alojamiento (Host Capacity)")
        sec.body_paragraphs.append(
            f"Se evaluó la capacidad máxima de PV y carga adicional "
            f"que cada bus puede recibir sin violar normativa, "
            f"considerando {hr.n_hours_simulated_per_iteration} horas "
            f"críticas. Total {hr.n_buses_analyzed} buses analizados en "
            f"{hr.elapsed_seconds:.1f} segundos."
        )
        sec.tables.append({
            "title": "Capacidad máxima por bus (kW)",
            "headers": ["Bus", "V nom (kV)", "PV máx (kW)", "Limita PV",
                        "Carga máx (kW)", "Limita Carga"],
            "rows": [
                [b.bus_id, f"{b.voltage_nominal_kv:.3f}",
                 f"{b.pv_hosting_kw:.1f}",
                 b.pv_limiting_factor.value,
                 f"{b.load_hosting_kw:.1f}",
                 b.load_limiting_factor.value]
                for b in hr.bus_results.values()
            ],
        })
        return sec

    # =========================================================================
    # Sección: Recomendaciones
    # =========================================================================
    def _build_recommendations_section(self) -> ReportSection:
        sec = ReportSection(title="6. Recomendaciones")
        recs: List[str] = []

        # Generar recomendaciones basadas en hallazgos
        if self.ctx.has_compliance:
            for v in self.ctx.compliance_report.violations():
                if v.category == "voltaje":
                    recs.append(
                        f"Reforzar conductor o instalar regulador de "
                        f"tensión en {v.element_id} para corregir "
                        f"{v.message.lower()}."
                    )
                elif v.category == "ampacidad":
                    recs.append(
                        f"Reemplazar el elemento {v.element_id} por uno de "
                        f"mayor capacidad (carga actual: "
                        f"{v.actual_value:.1f}%)."
                    )
                elif v.category == "perdidas":
                    recs.append(
                        "Optimizar topología o ubicación de transformadores "
                        "para reducir pérdidas técnicas globales."
                    )

        if self.ctx.has_annual:
            ar = self.ctx.annual_results
            if ar.peak_transformer_loading_pct > 100:
                recs.append(
                    f"El transformador {ar.peak_transformer_id} excede su "
                    f"capacidad nominal en hora(s) pico. Recomendamos "
                    f"aumentar capacidad o instalar BESS para peak shaving."
                )

        if self.ctx.has_hosting:
            saturated = [
                b for b in self.ctx.hosting_results.bus_results.values()
                if b.pv_hosting_kw < 10.0
            ]
            if saturated:
                recs.append(
                    f"{len(saturated)} bus(es) están saturados para nueva "
                    "generación PV. Considerar limitar nuevas autorizaciones "
                    "o reforzar la red aguas arriba antes de expandir."
                )

        if not recs:
            recs.append(
                "La red presenta un comportamiento aceptable. Se recomienda "
                "mantener el monitoreo periódico y actualizar el análisis "
                "anualmente o ante cambios significativos de demanda."
            )
        sec.body_paragraphs = recs
        return sec
