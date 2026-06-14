# -*- coding: utf-8 -*-
"""
redes_engine.engineering.mechanical
====================================

Cálculo mecánico de conductores aéreos.

Implementa:
    - Ecuación de Estado del Conductor (EEC):
        T2[L²w2²/(24T2²) − ε(T2−T1)] = T1[L²w1²/(24T1²)] + L²(w2²−w1²)/24
    - Flecha por catenaria:
        f = w·L²/(8·T)
    - Esfuerzos máximos por viento + temperatura

Basado en GUIA EEASA 2021 Parte III - Cap. 7 y RTE INEN 083.
Algoritmos sin dependencia de QGIS, OpenDSS o NumPy/SciPy
(implementación pura de Python para máxima portabilidad).
"""

import math
import warnings
from dataclasses import dataclass
from typing import Optional


# =============================================================================
# Datos del conductor
# =============================================================================
@dataclass
class ConductorProperties:
    """Propiedades físicas del conductor."""
    name: str                       # ej. "ACSR_4/0AWG_Penguin"
    section_mm2: float              # sección equivalente
    diameter_mm: float
    weight_kg_m: float              # peso por metro
    rated_strength_kN: float        # carga de rotura
    elastic_modulus_GPa: float = 68.9
    thermal_expansion_coef: float = 1.93e-5    # 1/°C
    max_tension_pct: float = 0.20    # % de rated_strength como tensión nominal


@dataclass
class MechanicalState:
    """Estado de operación del conductor en un vano."""
    span_m: float                   # longitud del vano
    temperature_c: float
    wind_pressure_pa: float = 0.0   # presión de viento
    ice_thickness_mm: float = 0.0
    tension_n: Optional[float] = None   # tensión axial (N) — calculada por EEC


@dataclass
class SagResult:
    """Resultado del cálculo de flecha."""
    sag_m: float                    # flecha máxima
    catenary_constant_m: float      # c = T/w
    tension_at_low_point_n: float
    tension_at_support_n: float
    arc_length_m: float


# =============================================================================
# Carga combinada (peso + viento + hielo)
# =============================================================================
def combined_unit_load_n_per_m(
    cp: ConductorProperties,
    wind_pressure_pa: float = 0.0,
    ice_thickness_mm: float = 0.0,
) -> float:
    """
    Carga unitaria total sobre el conductor (vector resultante de peso+viento).

    Ice load: capa anular de hielo de espesor e (mm), densidad 917 kg/m³.
    Wind load: presión q · diámetro_efectivo.
    """
    g = 9.81
    weight_n_per_m = cp.weight_kg_m * g

    # Hielo
    if ice_thickness_mm > 0:
        e_m = ice_thickness_mm / 1000.0
        d_m = cp.diameter_mm / 1000.0
        # área anular = π·e·(d+e)
        area_ice = math.pi * e_m * (d_m + e_m)
        weight_ice = 917.0 * area_ice * g  # N/m
        weight_n_per_m += weight_ice
        d_total_m = d_m + 2 * e_m
    else:
        d_total_m = cp.diameter_mm / 1000.0

    # Viento
    wind_n_per_m = wind_pressure_pa * d_total_m   # N/m horizontal

    return math.sqrt(weight_n_per_m ** 2 + wind_n_per_m ** 2)


# =============================================================================
# Ecuación de Estado del Conductor (EEC)
# =============================================================================
def solve_change_of_state(
    cp: ConductorProperties,
    state_initial: MechanicalState,
    state_final: MechanicalState,
    max_iterations: int = 200,
    tolerance_n: float = 0.5,
) -> float:
    """
    Resuelve la EEC numéricamente para encontrar T2 (tensión en estado final).

    Estado 1: temperatura, viento, hielo conocidos + T1 conocida.
    Estado 2: temperatura, viento, hielo conocidos + T2 INCÓGNITA.

    EEC reordenada como f(T2)=0:
        f(T2) = T2³ + T2²·[α·E·A·(t2−t1) + (L²w1²·E·A)/(24·T1²) − T1]
                − E·A·L²·w2²/24 = 0

    Resuelto vía bisección (más robusto que Newton para casos extremos).
    """
    # Calcular cargas unitarias en cada estado
    w1 = combined_unit_load_n_per_m(cp,
        state_initial.wind_pressure_pa,
        state_initial.ice_thickness_mm,
    )
    w2 = combined_unit_load_n_per_m(cp,
        state_final.wind_pressure_pa,
        state_final.ice_thickness_mm,
    )
    L = state_final.span_m
    if L <= 0 or state_initial.tension_n is None or state_initial.tension_n <= 0:
        raise ValueError("span > 0 y T1 > 0 requeridos")

    T1 = state_initial.tension_n
    t1, t2 = state_initial.temperature_c, state_final.temperature_c

    # E·A en N (convertir GPa·mm² a N)
    EA = cp.elastic_modulus_GPa * 1000.0 * cp.section_mm2  # GPa·mm² = N
    alpha = cp.thermal_expansion_coef

    # Forma cúbica clásica de la EEC (Wagner-Webster):
    #   T2³ + b·T2² − c = 0
    # donde
    #   b = EA·L²·w1²/(24·T1²) + EA·α·(t2−t1) − T1
    #   c = EA·L²·w2² / 24
    b = EA * (L * w1) ** 2 / (24.0 * T1 ** 2) + EA * alpha * (t2 - t1) - T1
    c = EA * (L * w2) ** 2 / 24.0

    def g(T2: float) -> float:
        return T2 ** 3 + b * T2 ** 2 - c

    # La rama física monotónicamente creciente está después del crítico
    # T_crit = -2b/3 (donde g'(T)=0). Para b<0 (caso usual), T_crit>0.
    # Usamos bisección en [max(T_crit, T1·0.1), 2·rated_max] donde g es creciente
    rated_max = cp.rated_strength_kN * 1000.0
    T_crit = max(0.0, -2.0 * b / 3.0)
    lo = max(T_crit + 1.0, T1 * 0.1, 10.0)
    hi = max(T1 * 10.0, rated_max * 2.0)

    # Asegurar bracket válido
    while g(lo) > 0 and lo > 10.0:
        lo /= 2.0
    while g(hi) < 0 and hi < rated_max * 100:
        hi *= 2.0

    g_lo = g(lo)
    g_hi = g(hi)
    if g_lo * g_hi > 0:
        # Sin cambio de signo en la rama física: la EEC no converge para estos
        # datos. Avisamos en vez de enmascarar la no-convergencia como si la
        # tensión "no cambiara".
        warnings.warn(
            "solve_change_of_state: no se encontró raíz en la rama física "
            f"(T1={T1:.1f} N, L={L:.1f} m, t1={t1}°C→t2={t2}°C). "
            "Se devuelve T1 como fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return T1

    for _ in range(max_iterations):
        mid = (lo + hi) / 2.0
        gm = g(mid)
        if (hi - lo) < tolerance_n:
            return mid
        if g_lo * gm < 0:
            hi = mid
            g_hi = gm
        else:
            lo = mid
            g_lo = gm
    return (lo + hi) / 2.0


# =============================================================================
# Flecha por catenaria
# =============================================================================
def compute_sag(
    cp: ConductorProperties,
    state: MechanicalState,
    use_parabolic: bool = False,
) -> SagResult:
    """
    Calcula la flecha máxima de un conductor en un vano.

    Por defecto usa la ecuación de la CATENARIA (exacta):
        y(x) = c · cosh(x/c) − c
        donde c = T_horizontal / w (constante de catenaria)
        f_max = c·(cosh(L/(2c)) − 1)

    Si use_parabolic=True, usa la aproximación parabólica (menor precisión
    pero válida para vanos cortos):
        f_max = w·L² / (8·T)
    """
    if state.tension_n is None or state.tension_n <= 0:
        raise ValueError("state.tension_n debe estar definido y > 0")

    w = combined_unit_load_n_per_m(cp, state.wind_pressure_pa, state.ice_thickness_mm)
    if w <= 0:
        raise ValueError("Carga unitaria debe ser > 0")
    L = state.span_m
    T = state.tension_n

    if use_parabolic:
        sag = w * L * L / (8.0 * T)
        c = T / w
        T_low = T
        T_sup = T + w * sag
        arc_len = L + (8.0 * sag * sag) / (3.0 * L)   # aprox.
    else:
        c = T / w
        sag = c * (math.cosh(L / (2.0 * c)) - 1.0)
        T_low = T   # tensión horizontal mínima al pie del vano
        # Tensión en el apoyo: T_sup = T_low · cosh(L/2c)
        T_sup = T_low * math.cosh(L / (2.0 * c))
        # Longitud del arco
        arc_len = 2.0 * c * math.sinh(L / (2.0 * c))

    return SagResult(
        sag_m=sag,
        catenary_constant_m=c,
        tension_at_low_point_n=T_low,
        tension_at_support_n=T_sup,
        arc_length_m=arc_len,
    )


# =============================================================================
# Tensión máxima del conductor
# =============================================================================
def compute_max_tension(cp: ConductorProperties) -> float:
    """Tensión máxima permitida en el conductor (N)."""
    return cp.rated_strength_kN * 1000.0 * cp.max_tension_pct
