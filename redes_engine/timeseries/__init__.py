# -*- coding: utf-8 -*-
"""
redes_engine.timeseries
========================

Análisis de series temporales 8760h (un año de operación hora-a-hora).

Arquitectura:
    profiles.py    — generadores de perfiles 8760h (residencial, PV, VE, BESS)
    scenarios.py   — escenarios de penetración (VE/PV multianual)
    solver.py      — TimeSeriesSolver eficiente con OpenDSS loadshapes
    aggregator.py  — estadísticas anuales (picos, horas violación, energía)

Caso de uso típico:
    profiles = ProfileLibrary.ecuador_default()
    scenario = Scenario(year=2030, ev_penetration_pct=25, pv_penetration_pct=20)
    solver = TimeSeriesSolver(network, profiles, scenario)
    annual = solver.run()
    print(annual.summary())
"""

from .aggregator import AnnualResults, BranchAnnualStats, BusAnnualStats
from .profiles import (
    HOURS_PER_DAY,
    HOURS_PER_YEAR,
    ProfileGenerator,
    ProfileLibrary,
)
from .scenarios import Scenario, ScenarioComparison
from .solver import TimeSeriesSolver
from .stratified import (
    EV_ADOPTION_WEIGHTS,
    EV_KWH_PER_DAY_BY_STRATUM,
    PV_ADOPTION_WEIGHTS,
    PV_KWP_BY_STRATUM,
    expected_ev_kwh_per_day_for,
    expected_kwp_for,
    stratified_sample,
    stratum_distribution,
)

__all__ = [
    "ProfileGenerator", "ProfileLibrary",
    "HOURS_PER_YEAR", "HOURS_PER_DAY",
    "Scenario", "ScenarioComparison",
    "TimeSeriesSolver",
    "AnnualResults", "BusAnnualStats", "BranchAnnualStats",
    # Estratificación socioeconómica
    "stratified_sample", "stratum_distribution",
    "EV_ADOPTION_WEIGHTS", "PV_ADOPTION_WEIGHTS",
    "EV_KWH_PER_DAY_BY_STRATUM", "PV_KWP_BY_STRATUM",
    "expected_kwp_for", "expected_ev_kwh_per_day_for",
]
