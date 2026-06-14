# -*- coding: utf-8 -*-
"""
redes_engine.engineering.protections
=====================================

Cálculos de protecciones eléctricas en redes de distribución:

    - Corriente de cortocircuito 3φ y 1φ-tierra
    - Curvas tiempo-corriente IEC 60255 (NI, VI, EI, LTI)
    - Selección de fusible por demanda
    - Coordinación primaria-respaldo (margen de tiempo)

Sin dependencia de OpenDSS — fórmulas analíticas estándar.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple


# =============================================================================
# Curvas tiempo-corriente IEC 60255
# =============================================================================
class CurveType(Enum):
    """Curvas tiempo-corriente estándar IEC."""
    INVERSE_NORMAL = "ni"          # Normal Inverse: t = 0.14·TMS / (M^0.02 − 1)
    INVERSE_VERY = "vi"            # Very Inverse:   t = 13.5·TMS / (M − 1)
    INVERSE_EXTREMELY = "ei"       # Extremely Inv.: t = 80·TMS / (M² − 1)
    INVERSE_LONG_TIME = "lti"      # Long Time Inv.: t = 120·TMS / (M − 1)
    DEFINITE = "definite"          # Tiempo definido (t fijo)


# Coeficientes IEC 60255-3 (a, b)
_IEC_COEFS = {
    CurveType.INVERSE_NORMAL:    (0.14, 0.02),
    CurveType.INVERSE_VERY:      (13.5, 1.0),
    CurveType.INVERSE_EXTREMELY: (80.0, 2.0),
    CurveType.INVERSE_LONG_TIME: (120.0, 1.0),
}


def operating_time(
    curve: CurveType,
    fault_current_a: float,
    pickup_a: float,
    tms: float = 0.1,
    definite_time_s: float = 0.5,
) -> float:
    """
    Tiempo de operación de una protección IEC 60255.

    Parameters
    ----------
    curve : CurveType
    fault_current_a : float
        Corriente de falla observada por el relé.
    pickup_a : float
        Corriente de arranque (tap setting).
    tms : float
        Time Multiplier Setting.
    definite_time_s : float
        Tiempo si la curva es DEFINITE.

    Returns
    -------
    float : tiempo de operación en segundos. Inf si M ≤ 1 (no opera).
    """
    if curve == CurveType.DEFINITE:
        return definite_time_s if fault_current_a >= pickup_a else float("inf")

    if pickup_a <= 0:
        return float("inf")
    M = fault_current_a / pickup_a   # múltiplo de pickup
    if M <= 1.0:
        return float("inf")
    a, b = _IEC_COEFS[curve]
    return a * tms / (M ** b - 1.0)


# =============================================================================
# Corrientes de cortocircuito
# =============================================================================
@dataclass
class FaultCalculation:
    """Resultado del cálculo de cortocircuito."""
    fault_type: str
    voltage_kv: float
    impedance_ohm: float
    current_ka: float
    power_mva: float


def fault_current_3phase(
    voltage_kv: float,
    impedance_pu: float,
    base_mva: float = 100.0,
) -> FaultCalculation:
    """
    Corriente de cortocircuito trifásico simétrico.

    I_3φ = V_LL / (√3 · Z)
    """
    if impedance_pu <= 0:
        raise ValueError("impedance_pu debe ser > 0")
    base_impedance = (voltage_kv ** 2) / base_mva
    z_ohm = impedance_pu * base_impedance
    i_a = (voltage_kv * 1000.0) / (math.sqrt(3) * z_ohm)
    s_mva = math.sqrt(3) * voltage_kv * (i_a / 1000.0)
    return FaultCalculation(
        fault_type="3-phase",
        voltage_kv=voltage_kv,
        impedance_ohm=z_ohm,
        current_ka=i_a / 1000.0,
        power_mva=s_mva,
    )


def fault_current_phase_to_ground(
    voltage_kv: float,
    z1_pu: float,
    z2_pu: float,
    z0_pu: float,
    base_mva: float = 100.0,
) -> FaultCalculation:
    """
    Corriente de cortocircuito fase-tierra.

    I_1φ = 3·V_fase / (Z1 + Z2 + Z0)
    """
    z_total_pu = z1_pu + z2_pu + z0_pu
    if z_total_pu <= 0:
        raise ValueError("Suma Z1+Z2+Z0 debe ser > 0")
    base_impedance = (voltage_kv ** 2) / base_mva
    z_ohm = z_total_pu * base_impedance
    # I_1φ = 3·V_fase / |Z1+Z2+Z0|  (forma directa, sin pasos redundantes)
    v_phase = voltage_kv / math.sqrt(3) * 1000.0   # V fase-neutro
    i_1phase_a = 3.0 * v_phase / z_ohm
    i_ka = i_1phase_a / 1000.0
    # Potencia de cortocircuito trifásica equivalente (S = √3·V_LL·I),
    # coherente con la definición usada en fault_current_3phase.
    s_mva = math.sqrt(3) * voltage_kv * i_ka
    return FaultCalculation(
        fault_type="phase-ground",
        voltage_kv=voltage_kv,
        impedance_ohm=z_ohm,
        current_ka=i_ka,
        power_mva=s_mva,
    )


# =============================================================================
# Selección de fusible por demanda
# =============================================================================
@dataclass
class ProtectionDevice:
    """Dispositivo de protección."""
    name: str
    rated_a: float                  # corriente nominal
    breaking_ka: float              # capacidad de interrupción
    curve: CurveType = CurveType.INVERSE_NORMAL
    tms: float = 0.1                # solo para reclosers
    pickup_a: Optional[float] = None
    is_fuse: bool = False


# Calibres comerciales típicos de fusibles (NEMA T-link)
_FUSE_RATINGS_A = [
    1, 2, 3, 5, 8, 10, 12, 15, 20, 25, 30, 40, 50, 65, 80, 100, 140, 200,
]


def select_fuse_for_load(
    load_kva: float,
    voltage_kv: float,
    safety_factor: float = 1.4,
) -> ProtectionDevice:
    """
    Selecciona el fusible NEMA T más pequeño que cubra la carga
    con factor de seguridad (default 1.4 × demanda).

    Returns
    -------
    ProtectionDevice
    """
    if voltage_kv <= 0:
        raise ValueError("voltage_kv > 0")
    nominal_current_a = (load_kva / (math.sqrt(3) * voltage_kv))
    target = nominal_current_a * safety_factor

    for rating in _FUSE_RATINGS_A:
        if rating >= target:
            return ProtectionDevice(
                name=f"NEMA T {rating}A",
                rated_a=float(rating),
                breaking_ka=8.0,    # típico para distribución MT
                is_fuse=True,
            )
    # Si excede, devolver el mayor disponible
    return ProtectionDevice(
        name=f"NEMA T {_FUSE_RATINGS_A[-1]}A (revisar)",
        rated_a=float(_FUSE_RATINGS_A[-1]),
        breaking_ka=8.0,
        is_fuse=True,
    )


# =============================================================================
# Coordinación de curvas
# =============================================================================
def coordinate_curves(
    primary: ProtectionDevice,
    backup: ProtectionDevice,
    fault_currents_a: List[float],
    margin_s: float = 0.3,
) -> List[Tuple[float, bool, str]]:
    """
    Verifica coordinación entre dos protecciones para una lista de corrientes.

    Returns
    -------
    List[(I_falla, ¿coordina?, mensaje)]
    """
    results = []
    for I in fault_currents_a:
        t_primary = operating_time(
            primary.curve, I,
            primary.pickup_a or primary.rated_a,
            primary.tms,
        )
        t_backup = operating_time(
            backup.curve, I,
            backup.pickup_a or backup.rated_a,
            backup.tms,
        )
        if t_primary == float("inf") and t_backup == float("inf"):
            results.append((I, False, "Ningún dispositivo opera"))
            continue
        if t_primary == float("inf"):
            results.append((I, False, "Primaria no opera"))
            continue
        if t_backup == float("inf"):
            results.append((I, True, f"Solo opera primaria t={t_primary:.3f}s"))
            continue
        diff = t_backup - t_primary
        coordinates = diff >= margin_s
        msg = (
            f"t_pri={t_primary:.3f}s, t_back={t_backup:.3f}s, "
            f"Δt={diff:.3f}s ({'OK' if coordinates else 'sin margen'})"
        )
        results.append((I, coordinates, msg))
    return results
