# -*- coding: utf-8 -*-
"""
redes_engine.engineering.ampacity
==================================

Cálculo simplificado de ampacidad de cables subterráneos según el método
Neher-McGrath (IEEE Std 835-1994), versión simplificada que da resultados
aceptables para diseño de distribución.

Método completo Neher-McGrath está en cables_aprovados.org/iec_60287
y requiere modelado térmico complejo. Esta implementación cubre:

    - Ampacidad base del cable según fabricante
    - Derate por temperatura ambiente diferente al estándar
    - Derate por agrupación (varios cables en banco de ductos)
    - Derate por profundidad de instalación
    - Derate por resistividad térmica del terreno

Para cables aéreos use la corriente nominal del catálogo del conductor;
no se requiere derate térmico (el aire disipa calor naturalmente).
"""

from dataclasses import dataclass


# =============================================================================
# Datos de entrada
# =============================================================================
@dataclass
class CableConfig:
    """Configuración de instalación de un cable subterráneo."""
    cable_name: str
    rated_ampacity_a: float           # ampacidad base del fabricante (a 20°C suelo)
    rated_temp_soil_c: float = 20.0   # temperatura suelo de referencia
    rated_max_temp_c: float = 90.0    # temp máx del aislamiento (XLPE típico)
    n_circuits_in_duct_bank: int = 1  # cables en mismo banco de ductos
    burial_depth_m: float = 1.0
    soil_thermal_resistivity_km_per_w: float = 1.0   # típico 0.9-1.2


@dataclass
class AmpacityResult:
    """Resultado del cálculo de ampacidad."""
    cable_name: str
    rated_ampacity_a: float
    derate_factor_temp: float
    derate_factor_grouping: float
    derate_factor_depth: float
    derate_factor_soil: float
    total_derate_factor: float
    final_ampacity_a: float


# =============================================================================
# Factores de derate (tabla simplificada)
# =============================================================================

# Derate por temperatura ambiente (suelo) — ratio a temp nominal
# Aproximación: F_temp = sqrt((T_max − T_soil) / (T_max − T_soil_ref))
def derate_for_temperature(
    soil_temp_c: float,
    cable_max_temp_c: float = 90.0,
    rated_soil_temp_c: float = 20.0,
) -> float:
    if soil_temp_c >= cable_max_temp_c:
        return 0.0   # imposible operar
    available = cable_max_temp_c - soil_temp_c
    nominal = cable_max_temp_c - rated_soil_temp_c
    if nominal <= 0:
        return 1.0
    return (available / nominal) ** 0.5


# Tabla de derate por agrupación (NEC Table 310.15(B)(3)(a) simplificada)
_GROUPING_DERATE = {
    1: 1.00,
    2: 0.85,
    3: 0.78,
    4: 0.74,
    5: 0.70,
    6: 0.67,
    7: 0.65,
    8: 0.63,
    9: 0.60,
}


def derate_for_grouping(n_circuits: int) -> float:
    """Factor de derate por número de circuitos en mismo banco."""
    if n_circuits <= 0:
        return 1.0
    if n_circuits in _GROUPING_DERATE:
        return _GROUPING_DERATE[n_circuits]
    if n_circuits > 9:
        return 0.55   # casos extremos
    return 1.0


def derate_for_depth(burial_depth_m: float) -> float:
    """
    Derate por profundidad de enterramiento.
    Profundidad estándar: 1.0 m. A mayor profundidad, peor disipación.
        - 0.5-1.0 m: factor 1.0
        - 1.0-1.5 m: factor 0.97
        - 1.5-2.0 m: factor 0.93
        - >2.0 m:    factor 0.90
    """
    if burial_depth_m <= 1.0:
        return 1.0
    if burial_depth_m <= 1.5:
        return 0.97
    if burial_depth_m <= 2.0:
        return 0.93
    return 0.90


def derate_for_soil_resistivity(rho_km_per_w: float) -> float:
    """
    Derate por resistividad térmica del suelo.
    Valor de referencia: 1.0 K·m/W (suelo húmedo medio).
        - 0.5: factor 1.10 (suelo muy conductor — arena húmeda)
        - 1.0: factor 1.00
        - 1.5: factor 0.92
        - 2.0: factor 0.85
        - 3.0: factor 0.75
    """
    if rho_km_per_w <= 0.5:
        return 1.10
    if rho_km_per_w <= 1.0:
        return 1.00
    if rho_km_per_w <= 1.5:
        return 0.92
    if rho_km_per_w <= 2.0:
        return 0.85
    return 0.75


# =============================================================================
# Cálculo combinado
# =============================================================================
def compute_ampacity_underground(
    cfg: CableConfig,
    soil_temp_c: float = 20.0,
) -> AmpacityResult:
    """
    Calcula la ampacidad efectiva del cable en su instalación,
    aplicando todos los factores de derate.
    """
    f_temp = derate_for_temperature(
        soil_temp_c, cfg.rated_max_temp_c, cfg.rated_temp_soil_c,
    )
    f_group = derate_for_grouping(cfg.n_circuits_in_duct_bank)
    f_depth = derate_for_depth(cfg.burial_depth_m)
    f_soil = derate_for_soil_resistivity(cfg.soil_thermal_resistivity_km_per_w)

    total = f_temp * f_group * f_depth * f_soil
    final_a = cfg.rated_ampacity_a * total

    return AmpacityResult(
        cable_name=cfg.cable_name,
        rated_ampacity_a=cfg.rated_ampacity_a,
        derate_factor_temp=round(f_temp, 4),
        derate_factor_grouping=round(f_group, 4),
        derate_factor_depth=round(f_depth, 4),
        derate_factor_soil=round(f_soil, 4),
        total_derate_factor=round(total, 4),
        final_ampacity_a=round(final_a, 1),
    )
