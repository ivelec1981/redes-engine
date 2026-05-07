# -*- coding: utf-8 -*-
"""
redes_engine.timeseries.stratified
====================================

Distribución estratificada de penetración VE/PV según perfil socioeconómico.

En Ecuador (clasificación INEC) los estratos son:
    A   (alto)        ≈ 1.9% de hogares
    B   (medio-alto)  ≈ 11.2%
    C+  (medio)       ≈ 22.8%
    C-  (medio-bajo)  ≈ 49.3%
    D   (bajo)        ≈ 14.9%

Codificación numérica usada en `Asset.socioeconomic_stratum`:
    5=A, 4=B, 3=C+, 2=C-, 1=D, None=desconocido

Probabilidades relativas de adopción (calibradas con BAU EEASA / ARCERNNR):

VE  (correlación fuerte con ingreso): A=1.00, B=0.55, C+=0.20, C-=0.05, D=0.01
PV  (correlación con techo + ingreso): A=0.85, B=1.00, C+=0.70, C-=0.30, D=0.10
    PV pico en B porque C+ aún tiene techo pero menos capital;
    A vive en altos pisos sin techo propio frecuente.

Si un asset no tiene `socioeconomic_stratum` se le asigna el peso medio.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence


# =============================================================================
# Pesos relativos de adopción por estrato
# =============================================================================
EV_ADOPTION_WEIGHTS: Dict[int, float] = {
    5: 1.00,   # A
    4: 0.55,   # B
    3: 0.20,   # C+
    2: 0.05,   # C-
    1: 0.01,   # D
}

PV_ADOPTION_WEIGHTS: Dict[int, float] = {
    5: 0.85,   # A
    4: 1.00,   # B
    3: 0.70,   # C+
    2: 0.30,   # C-
    1: 0.10,   # D
}

# Capacidad PV típica por estrato (kWp) — refleja que estratos altos
# instalan sistemas mayores.
PV_KWP_BY_STRATUM: Dict[int, float] = {
    5: 8.0,
    4: 6.0,
    3: 4.5,
    2: 3.0,
    1: 2.0,
}

# Consumo VE diario por estrato (kWh) — vehículos más grandes en estratos altos.
EV_KWH_PER_DAY_BY_STRATUM: Dict[int, float] = {
    5: 30.0,
    4: 25.0,
    3: 22.0,
    2: 18.0,
    1: 14.0,
}


# =============================================================================
# Muestreo estratificado
# =============================================================================
def _weight_of(asset, weights: Dict[int, float], default_weight: float) -> float:
    """Peso de adopción para un asset; usa default si no tiene estrato."""
    s = getattr(asset, "socioeconomic_stratum", None)
    if s is None:
        return default_weight
    return weights.get(int(s), default_weight)


def stratified_sample(
    candidates: Sequence,
    n_to_select: int,
    weights: Dict[int, float],
    rng: random.Random,
    default_weight: Optional[float] = None,
    require_attribute: Optional[str] = None,
) -> List:
    """
    Selecciona `n_to_select` candidatos sin reemplazo, ponderado por estrato.

    Implementa el método de Efraimidis-Spirakis (clave aleatoria u^(1/w)),
    que es óptimo para muestreo ponderado sin reemplazo.

    Parameters
    ----------
    candidates : Sequence[Asset]
        Pool de candidatos.
    n_to_select : int
        Cantidad deseada (se trunca al tamaño del pool si es mayor).
    weights : Dict[int, float]
        Mapa estrato → peso (e.g. EV_ADOPTION_WEIGHTS).
    rng : random.Random
        Generador determinista.
    default_weight : float, optional
        Peso a asignar a candidatos sin estrato. Si None, usa el promedio
        de `weights`.
    require_attribute : str, optional
        Filtra candidatos que no cumplan `getattr(c, require_attribute)`
        (verdadero). Útil para PV que requiere `has_roof_pv_potential`.
    """
    if n_to_select <= 0 or not candidates:
        return []

    if default_weight is None:
        default_weight = (
            sum(weights.values()) / len(weights) if weights else 1.0
        )

    pool = list(candidates)
    if require_attribute is not None:
        # Si el atributo es None se asume "permitido" (datos incompletos)
        pool = [
            c for c in pool
            if getattr(c, require_attribute, None) in (True, None)
        ]
        if not pool:
            return []

    # Llaves Efraimidis-Spirakis: k = u^(1/w), seleccionar las k más altas
    keys = []
    for c in pool:
        w = max(_weight_of(c, weights, default_weight), 1e-9)
        u = rng.random()
        # u^(1/w) — equivalente a (1/w) * log(u) en log-space
        try:
            key = u ** (1.0 / w)
        except (ZeroDivisionError, OverflowError):
            key = 0.0
        keys.append((key, c))

    keys.sort(key=lambda t: t[0], reverse=True)
    n = min(n_to_select, len(keys))
    return [c for _, c in keys[:n]]


# =============================================================================
# Helpers de inspección
# =============================================================================
def stratum_distribution(assets: Sequence) -> Dict[Optional[int], int]:
    """Cuenta cuántos assets hay en cada estrato (incluye None)."""
    counts: Dict[Optional[int], int] = {}
    for a in assets:
        s = getattr(a, "socioeconomic_stratum", None)
        counts[s] = counts.get(s, 0) + 1
    return counts


def expected_kwp_for(asset, default_kwp: float = 5.0) -> float:
    """kWp recomendado para PV en un asset según estrato (o default)."""
    s = getattr(asset, "socioeconomic_stratum", None)
    if s is None:
        return default_kwp
    return PV_KWP_BY_STRATUM.get(int(s), default_kwp)


def expected_ev_kwh_per_day_for(asset, default_kwh: float = 22.0) -> float:
    """Consumo VE diario para un asset según estrato (o default)."""
    s = getattr(asset, "socioeconomic_stratum", None)
    if s is None:
        return default_kwh
    return EV_KWH_PER_DAY_BY_STRATUM.get(int(s), default_kwh)
