# -*- coding: utf-8 -*-
"""
redes_engine.engineering
=========================

Cálculos clásicos de ingeniería eléctrica de distribución, migrados desde
el plugin legacy a redes_engine para que estén disponibles standalone:

    - mechanical.py    Ecuación de Estado del Conductor (catenary, sag, viento)
    - protections.py   Coordinación de protecciones, corriente de cortocircuito
    - ampacity.py      Ampacidad de cables subterráneos (Neher-McGrath simplificado)
    - budget.py        Presupuesto UP→UC→BOM (manuales EEQ B-11, B-14)

Módulos puramente computacionales — sin UI, sin OpenDSS, sin QGIS.
"""

from .mechanical import (
    ConductorProperties, MechanicalState, SagResult,
    solve_change_of_state, compute_sag, compute_max_tension,
)
from .protections import (
    CurveType, ProtectionDevice, FaultCalculation,
    fault_current_3phase, fault_current_phase_to_ground,
    select_fuse_for_load, coordinate_curves,
)
from .ampacity import (
    CableConfig, AmpacityResult,
    compute_ampacity_underground, derate_for_temperature,
)
from .budget import (
    UPItem, UCItem, BOMItem, BOMResult,
    BudgetEngine,
)
from .investment import (
    CashFlow, InvestmentAnalyzer, InvestmentAssumptions, InvestmentResult,
    irr, npv, payback_period,
)
from .substation import (
    FeederBay, PowerTransformer, STANDARD_TRANSFORMER_RATINGS_MVA,
    Substation, SubstationStatus, SubstationTopology,
    detect_substations, select_transformer_for_load,
)

__all__ = [
    # Mechanical
    "ConductorProperties", "MechanicalState", "SagResult",
    "solve_change_of_state", "compute_sag", "compute_max_tension",
    # Protections
    "CurveType", "ProtectionDevice", "FaultCalculation",
    "fault_current_3phase", "fault_current_phase_to_ground",
    "select_fuse_for_load", "coordinate_curves",
    # Ampacity
    "CableConfig", "AmpacityResult",
    "compute_ampacity_underground", "derate_for_temperature",
    # Budget
    "UPItem", "UCItem", "BOMItem", "BOMResult",
    "BudgetEngine",
    # Investment
    "InvestmentAssumptions", "InvestmentAnalyzer", "InvestmentResult",
    "CashFlow", "npv", "irr", "payback_period",
    # Substation
    "Substation", "SubstationTopology", "SubstationStatus",
    "PowerTransformer", "FeederBay",
    "STANDARD_TRANSFORMER_RATINGS_MVA",
    "select_transformer_for_load", "detect_substations",
]
