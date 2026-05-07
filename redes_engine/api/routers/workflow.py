# -*- coding: utf-8 -*-
"""
redes_engine.api.routers.workflow
==================================

Endpoints del workflow v3.0:
    1. CAPTURA   — dibujo / importación de la red
    2. CÁLCULO   — flujo de potencia, hosting, 8760h
    3. VALIDAR   — compliance ARCERNNR
    4. EMITIR    — reportes PDF/Word/Excel
    5. OPERAR    — (futuro) integración SCADA

Y el panel de dominios activables:
    🟦 Aéreo MT   🟪 Aéreo BT   🟫 Subterráneo
    🟧 Subestaciones   🟩 Alumbrado   🟨 Generación Distribuida
"""

from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..storage import StoredNetwork, get_store


router = APIRouter(prefix="/api/v1/networks", tags=["workflow"])


# =============================================================================
# Schemas
# =============================================================================
class PhaseStatus(BaseModel):
    """Estado de una fase del workflow."""
    id: str               # "captura", "calculo", "validar", "emitir", "operar"
    name: str
    progress_pct: float   # 0-100
    completed_steps: List[str]
    pending_steps: List[str]
    is_unlocked: bool     # si está desbloqueada (depende de fases previas)


class WorkflowStatus(BaseModel):
    network_id: str
    active_phase: str
    phases: List[PhaseStatus]
    overall_progress_pct: float


class DomainStatus(BaseModel):
    """Estado de un dominio."""
    id: str               # "aereo_mt", "aereo_bt", "soterrado", ...
    name: str
    icon: str
    active: bool
    detected_in_network: bool   # si la red ya tiene elementos de este dominio
    n_elements: int             # cuántos elementos del dominio hay


class DomainsResponse(BaseModel):
    network_id: str
    domains: List[DomainStatus]


class DomainToggleRequest(BaseModel):
    domain_ids: List[str]
    active: bool


# =============================================================================
# Helpers
# =============================================================================
def _get_or_404(network_id: str) -> StoredNetwork:
    stored = get_store().get(network_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Network not found")
    return stored


def _compute_phase_captura(stored: StoredNetwork) -> Dict:
    """Fase 1: ¿la red está cargada?"""
    net = stored.network
    completed: List[str] = []
    pending: List[str] = []

    if len(net.buses) > 0:
        completed.append(f"{len(net.buses)} buses cargados")
    else:
        pending.append("Cargar buses (postes/medidores)")

    if len(net.branches) > 0:
        completed.append(f"{len(net.branches)} branches cargados")
    else:
        pending.append("Cargar branches (líneas/trafos)")

    if len(net.assets) > 0:
        completed.append(f"{len(net.assets)} assets cargados")
    else:
        pending.append("Cargar assets (cargas/VE/PV/BESS)")

    if net.is_connected():
        completed.append("Topología conexa")
    else:
        if len(net.buses) > 0:
            pending.append("Topología desconectada — revisar")

    total = 4
    pct = 100.0 * len(completed) / total if total else 0.0
    return {
        "completed": completed,
        "pending": pending,
        "progress_pct": pct,
    }


def _compute_phase_calculo(stored: StoredNetwork) -> Dict:
    """Fase 2: ¿qué análisis se han ejecutado?"""
    completed: List[str] = []
    pending: List[str] = []

    if stored.last_solve_result is not None:
        r = stored.last_solve_result
        completed.append(
            f"Flujo de potencia (pérdidas {r.losses_pct:.2f}%)"
        )
    else:
        pending.append("Ejecutar flujo de potencia")

    if stored.last_hosting_results is not None:
        h = stored.last_hosting_results
        completed.append(f"Host Capacity ({h.n_buses_analyzed} buses)")
    else:
        pending.append("Análisis Host Capacity")

    if stored.last_annual_results is not None:
        a = stored.last_annual_results
        completed.append(f"Análisis temporal {a.n_hours_simulated}h")
    else:
        pending.append("Análisis temporal 8760h")

    total = 3
    pct = 100.0 * len(completed) / total if total else 0.0
    return {"completed": completed, "pending": pending, "progress_pct": pct}


def _compute_phase_validar(stored: StoredNetwork) -> Dict:
    """Fase 3: ¿se evaluó cumplimiento normativo?"""
    completed: List[str] = []
    pending: List[str] = []

    if stored.last_compliance_report is not None:
        from ...core.results import ComplianceStatus
        c = stored.last_compliance_report
        n_viol = len(c.violations())
        n_warn = len(c.warnings())
        completed.append(
            f"Compliance ARCERNNR ({c.overall_status.value})"
        )
        if n_viol > 0:
            pending.append(f"Resolver {n_viol} violación(es) detectadas")
        if n_warn > 0:
            pending.append(f"Revisar {n_warn} advertencia(s)")
        if n_viol == 0 and n_warn == 0:
            completed.append("✓ Sin violaciones ni advertencias")
    else:
        pending.append("Evaluar compliance ARCERNNR")
        pending.append("Identificar violaciones")
        pending.append("Generar recomendaciones")

    total = 3
    pct = 100.0 * len(completed) / total if total else 0.0
    return {"completed": completed, "pending": pending, "progress_pct": pct}


def _compute_phase_emitir(stored: StoredNetwork) -> Dict:
    """Fase 4: ¿se generaron reportes?"""
    completed: List[str] = []
    pending: List[str] = []

    # Track de documentos emitidos (necesitamos un campo en StoredNetwork)
    docs = getattr(stored, "emitted_docs", [])
    if "pdf" in docs:
        completed.append("Reporte PDF generado")
    else:
        pending.append("Generar reporte PDF firmable")

    if "docx" in docs:
        completed.append("Reporte Word generado")
    else:
        pending.append("Generar reporte Word editable")

    if "rsproj" in docs:
        completed.append("Proyecto .rsproj guardado")
    else:
        pending.append("Guardar proyecto .rsproj")

    total = 3
    pct = 100.0 * len(completed) / total if total else 0.0
    return {"completed": completed, "pending": pending, "progress_pct": pct}


def _compute_phase_operar(stored: StoredNetwork) -> Dict:
    """Fase 5: futura integración con SCADA."""
    return {
        "completed": [],
        "pending": [
            "Integración SCADA (próximamente)",
            "Monitoreo en tiempo real",
            "Alarmas automáticas",
        ],
        "progress_pct": 0.0,
    }


# =============================================================================
# GET /networks/{id}/workflow
# =============================================================================
@router.get("/{network_id}/workflow", response_model=WorkflowStatus)
def get_workflow_status(network_id: str) -> WorkflowStatus:
    """
    Devuelve el progreso del workflow de 5 fases para esta red.
    """
    stored = _get_or_404(network_id)

    phases_data = [
        ("captura", "1. Captura", _compute_phase_captura(stored), True),
        ("calculo", "2. Cálculo", _compute_phase_calculo(stored), False),
        ("validar", "3. Validar", _compute_phase_validar(stored), False),
        ("emitir",  "4. Emitir",  _compute_phase_emitir(stored),  False),
        ("operar",  "5. Operar",  _compute_phase_operar(stored),  False),
    ]

    # Calcular desbloqueos (cada fase requiere ≥50% de la anterior)
    phases = []
    prev_progress = 100.0
    for pid, pname, pdata, _initial_unlock in phases_data:
        is_unlocked = (pid == "captura") or (prev_progress >= 50.0)
        phases.append(PhaseStatus(
            id=pid, name=pname,
            progress_pct=round(pdata["progress_pct"], 1),
            completed_steps=pdata["completed"],
            pending_steps=pdata["pending"],
            is_unlocked=is_unlocked,
        ))
        prev_progress = pdata["progress_pct"]

    # Fase activa = primera no-completada-y-desbloqueada
    active = "captura"
    for ph in phases:
        if ph.is_unlocked and ph.progress_pct < 100.0:
            active = ph.id
            break

    overall = sum(p.progress_pct for p in phases) / len(phases)

    return WorkflowStatus(
        network_id=network_id,
        active_phase=active,
        phases=phases,
        overall_progress_pct=round(overall, 1),
    )


# =============================================================================
# GET /networks/{id}/domains
# =============================================================================
DOMAINS_CATALOG = [
    ("aereo_mt",       "Aéreo MT",            "🟦"),
    ("aereo_bt",       "Aéreo BT",            "🟪"),
    ("soterrado",      "Subterráneo",         "🟫"),
    ("subestaciones",  "Subestaciones",       "🟧"),
    ("alumbrado",      "Alumbrado Público",   "🟩"),
    ("generacion_dg",  "Generación Distribuida", "🟨"),
]


def _detect_domains(stored: StoredNetwork) -> List[DomainStatus]:
    """Detecta qué dominios están presentes en la red."""
    from ...core.graph import AssetType, BranchType, BusType
    net = stored.network
    active_set = set(getattr(stored, "active_domains", []))

    # Contar elementos por dominio
    counts = {
        "aereo_mt": sum(
            1 for b in net.branches.values()
            if b.branch_type == BranchType.LINE_AEREA_MT
        ),
        "aereo_bt": sum(
            1 for b in net.branches.values()
            if b.branch_type == BranchType.LINE_AEREA_BT
        ),
        "soterrado": sum(
            1 for b in net.branches.values()
            if b.branch_type in (
                BranchType.LINE_SOTERRADA_MT, BranchType.LINE_SOTERRADA_BT,
            )
        ),
        "subestaciones": sum(
            1 for b in net.buses.values()
            if b.bus_type == BusType.BARRA_SE
        ),
        "alumbrado": sum(
            1 for a in net.assets.values()
            if a.asset_type == AssetType.ALUMBRADO_PUBLICO
        ),
        "generacion_dg": sum(
            1 for a in net.assets.values() if a.is_pv() or a.is_storage()
        ),
    }

    # Si no hay active_domains explicitos, todos los detectados están activos
    if not active_set:
        active_set = {k for k, c in counts.items() if c > 0}

    domains = []
    for did, name, icon in DOMAINS_CATALOG:
        n = counts.get(did, 0)
        domains.append(DomainStatus(
            id=did, name=name, icon=icon,
            active=did in active_set,
            detected_in_network=(n > 0),
            n_elements=n,
        ))
    return domains


@router.get("/{network_id}/domains", response_model=DomainsResponse)
def get_domains(network_id: str) -> DomainsResponse:
    stored = _get_or_404(network_id)
    return DomainsResponse(
        network_id=network_id,
        domains=_detect_domains(stored),
    )


@router.post("/{network_id}/domains")
def toggle_domains(network_id: str, req: DomainToggleRequest) -> DomainsResponse:
    """Activa o desactiva dominios para esta red."""
    stored = _get_or_404(network_id)

    valid_ids = {d[0] for d in DOMAINS_CATALOG}
    invalid = [d for d in req.domain_ids if d not in valid_ids]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Dominios desconocidos: {invalid}",
        )

    # Estado actual
    current = set(getattr(stored, "active_domains", []))
    if not current:
        current = {d.id for d in _detect_domains(stored) if d.detected_in_network}

    if req.active:
        current.update(req.domain_ids)
    else:
        current.difference_update(req.domain_ids)

    stored.active_domains = list(current)
    return DomainsResponse(
        network_id=network_id,
        domains=_detect_domains(stored),
    )
