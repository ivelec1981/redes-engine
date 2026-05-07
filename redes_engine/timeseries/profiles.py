# -*- coding: utf-8 -*-
"""
redes_engine.timeseries.profiles
=================================

Generadores de perfiles 8760h (un año de operación hora-a-hora).

Todos los perfiles se devuelven como listas de 8760 floats normalizados a 1.0
(multiplicar por la potencia nominal para obtener kW).

Catálogo Ecuador:
    - Residencial Sierra      (pico vespertino fuerte)
    - Residencial Costa       (pico vespertino + climatización)
    - Comercial               (horario laboral)
    - Industrial              (operación constante)
    - Alumbrado público       (solo de noche)
    - PV Sierra (Quito/Cuenca) — irradiancia ~5 kWh/m²/día
    - PV Costa (Guayaquil)    — irradiancia ~4.5 kWh/m²/día
    - PV Oriente (Pastaza)    — irradiancia ~4 kWh/m²/día (más nuboso)
    - EV residencial          (carga nocturna 19-6h)
    - EV DC fast público      (uniforme 6-22h con picos)
"""

import math
import random
from typing import Callable, Dict, List, Optional

# =============================================================================
# Constantes de tiempo
# =============================================================================
HOURS_PER_DAY = 24
DAYS_PER_YEAR = 365
HOURS_PER_YEAR = HOURS_PER_DAY * DAYS_PER_YEAR   # 8760


# =============================================================================
# GENERADOR DE PERFILES
# =============================================================================
class ProfileGenerator:
    """
    Construye perfiles 8760h con modulaciones diaria, semanal y estacional.

    Estructura del perfil:
        valor[h] = base_diaria(h%24) × factor_semanal × factor_estacional × ruido
    """

    def __init__(self, seed: Optional[int] = 42):
        self._rng = random.Random(seed)

    # =========================================================================
    # Builders fundamentales
    # =========================================================================
    def constant(self, value: float = 1.0) -> List[float]:
        """Perfil constante (carga industrial 24/7)."""
        return [value] * HOURS_PER_YEAR

    def diurnal_only(
        self, daily_pattern: List[float],
        weekly_factor: Optional[List[float]] = None,
        seasonal_amplitude: float = 0.0,
        seasonal_phase_days: int = 0,
        noise_pct: float = 0.0,
    ) -> List[float]:
        """
        Repite un patrón diario × factor semanal × factor estacional × ruido.

        Parameters
        ----------
        daily_pattern : list[float]
            24 valores [0,1] que se repiten cada día.
        weekly_factor : list[float] | None
            7 valores (lun-dom). None → todos 1.0 (sin diferencia).
        seasonal_amplitude : float
            Amplitud sinusoidal estacional. 0.1 = ±10% sobre el año.
        seasonal_phase_days : int
            Día del año en que ocurre el pico estacional.
        noise_pct : float
            Ruido gaussiano relativo. 0.05 = ±5%.
        """
        assert len(daily_pattern) == 24
        weekly = weekly_factor or [1.0] * 7
        assert len(weekly) == 7

        result = []
        for h in range(HOURS_PER_YEAR):
            day_of_year = h // HOURS_PER_DAY
            hour_of_day = h % HOURS_PER_DAY
            day_of_week = day_of_year % 7

            base = daily_pattern[hour_of_day]
            week_f = weekly[day_of_week]

            seasonal = 1.0
            if seasonal_amplitude != 0.0:
                # Sinusoide con período 365 días
                phase = 2 * math.pi * (day_of_year - seasonal_phase_days) / 365.0
                seasonal = 1.0 + seasonal_amplitude * math.cos(phase)

            noise = 1.0
            if noise_pct > 0.0:
                noise = 1.0 + self._rng.gauss(0, noise_pct)
                noise = max(0.0, noise)

            result.append(base * week_f * seasonal * noise)
        return result

    # =========================================================================
    # Perfiles solares (PV)
    # =========================================================================
    def solar_pv(
        self,
        latitude_deg: float = -2.0,        # Cuenca/Quito
        peak_irradiance_h: int = 12,
        sunrise_h: int = 6,
        sunset_h: int = 18,
        cloud_factor_mean: float = 0.85,   # Multiplicador medio (1.0 = cielo claro)
        cloud_factor_std: float = 0.20,
        seasonal_amplitude: float = 0.10,
        seasonal_phase_days: int = 80,    # Marzo (equinoccio austral)
    ) -> List[float]:
        """
        Genera perfil PV 8760h.
        Curva diaria: arco sinusoidal entre amanecer y atardecer.
        Modulación: nubosidad estocástica + variación estacional sinusoidal.
        """
        # Patrón diario base
        daily = []
        sun_hours = sunset_h - sunrise_h
        for h in range(HOURS_PER_DAY):
            if h < sunrise_h or h >= sunset_h:
                daily.append(0.0)
            else:
                # Arco sinusoidal: 0 al amanecer y atardecer, pico al mediodía
                t = (h + 0.5 - sunrise_h) / sun_hours   # [0, 1]
                daily.append(math.sin(t * math.pi))

        # Modulación día por día con nubes y estacional
        result = []
        for h in range(HOURS_PER_YEAR):
            day_of_year = h // HOURS_PER_DAY
            hour_of_day = h % HOURS_PER_DAY

            base = daily[hour_of_day]

            # Estacional: ±amplitud sinusoidal
            phase = 2 * math.pi * (day_of_year - seasonal_phase_days) / 365.0
            seasonal = 1.0 + seasonal_amplitude * math.cos(phase)

            # Nubosidad: mismo factor para todas las horas del día
            if hour_of_day == 0:
                self._daily_cloud = max(0.0, min(1.0,
                    self._rng.gauss(cloud_factor_mean, cloud_factor_std)))

            cloud = getattr(self, "_daily_cloud", cloud_factor_mean)
            result.append(base * seasonal * cloud)
        return result

    # =========================================================================
    # Perfiles de carga residencial
    # =========================================================================
    def residential_sierra(self, noise_pct: float = 0.05) -> List[float]:
        """Residencial Sierra (Quito/Cuenca). Pico nocturno marcado, sin AC."""
        daily = [
            # 0-5 madrugada: base mínima
            0.20, 0.18, 0.16, 0.15, 0.18, 0.25,
            # 6-8 desayuno
            0.45, 0.62, 0.50,
            # 9-11 mañana baja
            0.30, 0.27, 0.30,
            # 12-13 almuerzo
            0.45, 0.42,
            # 14-17 tarde baja
            0.30, 0.32, 0.40, 0.55,
            # 18-22 pico nocturno
            0.85, 1.00, 0.95, 0.85, 0.70,
            # 23 fin del día
            0.40,
        ]
        weekly = [1.0, 1.0, 1.0, 1.0, 1.0, 1.10, 1.05]   # más en sábado
        return self.diurnal_only(daily, weekly_factor=weekly,
                                  seasonal_amplitude=0.05,
                                  noise_pct=noise_pct)

    def residential_costa(self, noise_pct: float = 0.05) -> List[float]:
        """Residencial Costa (Guayaquil). Mayor base por climatización."""
        daily = [
            # AC sigue funcionando de noche en zonas calientes
            0.40, 0.38, 0.35, 0.35, 0.38, 0.42,
            0.50, 0.65, 0.55, 0.45, 0.50, 0.60,
            0.65, 0.60, 0.55, 0.60, 0.70, 0.85,
            1.00, 0.95, 0.90, 0.80, 0.65, 0.50,
        ]
        weekly = [1.0, 1.0, 1.0, 1.0, 1.0, 1.12, 1.08]
        return self.diurnal_only(daily, weekly_factor=weekly,
                                  seasonal_amplitude=0.15,
                                  seasonal_phase_days=30,   # más en Feb (verano costero)
                                  noise_pct=noise_pct)

    # =========================================================================
    # Perfiles de carga comercial / industrial
    # =========================================================================
    def commercial(self, noise_pct: float = 0.04) -> List[float]:
        """Comercial: horario laboral, baja en noches/fines de semana."""
        daily = [
            0.10, 0.10, 0.10, 0.10, 0.10, 0.15,
            0.30, 0.55, 0.85, 0.95, 1.00, 1.00,
            0.95, 1.00, 1.00, 0.95, 0.85, 0.65,
            0.40, 0.25, 0.20, 0.15, 0.12, 0.10,
        ]
        weekly = [1.0, 1.0, 1.0, 1.0, 1.0, 0.40, 0.20]   # caída fin de semana
        return self.diurnal_only(daily, weekly_factor=weekly,
                                  seasonal_amplitude=0.08,
                                  noise_pct=noise_pct)

    def industrial(self, shift_hours: int = 24,
                    noise_pct: float = 0.02) -> List[float]:
        """Industrial: 24/7 (3 turnos) o solo turno diurno."""
        if shift_hours >= 24:
            daily = [0.92] * HOURS_PER_DAY
        else:
            daily = [0.20] * HOURS_PER_DAY
            for h in range(8, 8 + shift_hours):
                daily[h % HOURS_PER_DAY] = 0.95
        weekly = [1.0] * 5 + [0.7, 0.5]
        return self.diurnal_only(daily, weekly_factor=weekly,
                                  noise_pct=noise_pct)

    # =========================================================================
    # Alumbrado público
    # =========================================================================
    def street_lighting(self) -> List[float]:
        """Alumbrado: solo encendido entre puesta y salida del sol."""
        daily = [1.0] * 6 + [0.0] * 12 + [1.0] * 6  # 0-5 ON, 6-17 OFF, 18-23 ON
        return self.diurnal_only(daily, noise_pct=0.0)

    # =========================================================================
    # Perfiles VE
    # =========================================================================
    def ev_residential(
        self,
        avg_arrival_hour: int = 19,
        avg_kwh_per_day: float = 22.0,
        rated_kw: float = 7.4,
        noise_pct: float = 0.10,
    ) -> List[float]:
        """
        VE residencial: carga nocturna principalmente.
        Devuelve perfil normalizado al rated_kw (valor 1.0 = a potencia nominal).
        """
        # Distribución: arrival ~Normal(avg_arrival_hour, 1.5h)
        # Charge time = avg_kwh_per_day / rated_kw
        charge_hours_per_day = avg_kwh_per_day / rated_kw

        result = []
        for day in range(DAYS_PER_YEAR):
            day_profile = [0.0] * HOURS_PER_DAY
            arrival = int(self._rng.gauss(avg_arrival_hour, 1.0))
            arrival = max(17, min(23, arrival))
            charge_dur = max(2, int(round(charge_hours_per_day)))
            for k in range(charge_dur):
                h = (arrival + k) % HOURS_PER_DAY
                # Modelo simple: carga constante a potencia nominal
                day_profile[h] = 1.0 * (1 + self._rng.gauss(0, noise_pct))
                day_profile[h] = max(0.0, min(1.0, day_profile[h]))
            result.extend(day_profile)
        return result

    def ev_dc_fast_public(
        self,
        sessions_per_day: int = 8,
        session_hours: float = 0.5,
    ) -> List[float]:
        """
        VE DC fast público: sesiones cortas distribuidas durante el día.
        """
        result = []
        for day in range(DAYS_PER_YEAR):
            day_profile = [0.0] * HOURS_PER_DAY
            for _ in range(sessions_per_day):
                # Sesión inicia entre 6-21h
                start = self._rng.randint(6, 21)
                # Distribuir energía en las horas de la sesión
                hours_used = max(1, int(round(session_hours)))
                for k in range(hours_used):
                    h = (start + k) % HOURS_PER_DAY
                    if h < HOURS_PER_DAY:
                        # Ocupación parcial — saturación a 1.0
                        day_profile[h] = min(1.0, day_profile[h] + 0.5)
            result.extend(day_profile)
        return result

    # =========================================================================
    # Perfiles VE comerciales: taxi / bus / flota corporativa
    # =========================================================================
    def ev_taxi(
        self,
        avg_kwh_per_day: float = 60.0,
        rated_kw: float = 50.0,
        charge_window: tuple = (1, 6),    # carga en madrugada (1-6h)
        sessions_per_day: int = 2,        # cargas rápidas durante el día
        noise_pct: float = 0.10,
    ) -> List[float]:
        """
        VE Taxi: uso intensivo durante el día, carga principal en madrugada
        + 1-2 cargas rápidas oportunistas al mediodía.

        Patrón típico Ecuador (Quito/Guayaquil):
            01:00-05:00 → carga depot a tarifa baja (60-70% energía)
            12:00-13:00 → carga rápida en almuerzo (15-20% energía)
            15:00-16:00 → carga rápida tarde (10-15% energía)
        """
        result = []
        ws, we = charge_window
        # Energía nocturna ≈ 70%, restante distribuido en sesiones rápidas
        night_kwh = avg_kwh_per_day * 0.70
        rapid_kwh = (avg_kwh_per_day - night_kwh) / max(1, sessions_per_day)

        for day in range(DAYS_PER_YEAR):
            day_profile = [0.0] * HOURS_PER_DAY

            # Carga nocturna distribuida en la ventana
            window_size = max(1, we - ws)
            kw_per_hour = night_kwh / window_size
            for h in range(ws, we):
                noise = 1.0 + self._rng.gauss(0, noise_pct)
                day_profile[h % HOURS_PER_DAY] = max(
                    0.0, min(1.0, kw_per_hour / rated_kw * noise)
                )

            # Cargas rápidas opportunistic
            rapid_slots = [12, 15, 18]
            chosen = self._rng.sample(rapid_slots, min(sessions_per_day, len(rapid_slots)))
            for h in chosen:
                day_profile[h % HOURS_PER_DAY] = max(
                    day_profile[h % HOURS_PER_DAY],
                    min(1.0, rapid_kwh / rated_kw)
                )

            result.extend(day_profile)
        return result

    def ev_bus(
        self,
        avg_kwh_per_day: float = 280.0,
        rated_kw: float = 150.0,
        depot_window: tuple = (23, 5),     # 23h-05h (cruza medianoche)
        noise_pct: float = 0.05,
    ) -> List[float]:
        """
        VE Bus eléctrico: rutas durante el día (descarga), carga de depot
        en horario nocturno fijo. Sin uso del cargador durante operación
        (la batería del bus se descarga vía consumo de tracción, no en este perfil).

        Genera el perfil del CARGADOR DE DEPOT, no de la batería del bus.
        """
        ws, we = depot_window
        if ws > we:
            # Ventana cruza medianoche
            window_hours = list(range(ws, HOURS_PER_DAY)) + list(range(0, we))
        else:
            window_hours = list(range(ws, we))

        kw_per_hour = avg_kwh_per_day / max(1, len(window_hours))
        normalized = min(1.0, kw_per_hour / rated_kw)

        result = []
        for day in range(DAYS_PER_YEAR):
            # Domingos y feriados: menos buses operando
            day_of_week = day % 7
            day_factor = 0.6 if day_of_week == 6 else 1.0   # domingo

            day_profile = [0.0] * HOURS_PER_DAY
            for h in window_hours:
                noise = 1.0 + self._rng.gauss(0, noise_pct)
                day_profile[h] = max(
                    0.0, min(1.0, normalized * day_factor * noise)
                )
            result.extend(day_profile)
        return result

    def ev_fleet_depot(
        self,
        n_vehicles: int = 20,
        avg_kwh_per_vehicle: float = 30.0,
        rated_kw_per_charger: float = 22.0,
        arrival_hour: int = 18,
        departure_hour: int = 6,
        noise_pct: float = 0.08,
    ) -> List[float]:
        """
        Flota corporativa (entregas, taxis ejecutivos, vehículos de servicio):
        Vehículos llegan al depot al final del día (17-19h), salen en la mañana
        (5-7h). Cargadores manejados por sistema de gestión de flota
        (escalonado para no exceder potencia contratada).

        Perfil normalizado al rated_kw_per_charger.
        """
        # Energía total nocturna por vehículo: avg_kwh_per_vehicle
        # Distribuir en la ventana arrival → departure
        if departure_hour < arrival_hour:
            window_hours = (
                list(range(arrival_hour, HOURS_PER_DAY)) +
                list(range(0, departure_hour))
            )
        else:
            window_hours = list(range(arrival_hour, departure_hour))
        n_window = len(window_hours)

        # Energía total flota / horas / cargadores → factor de uso
        total_kwh_per_day = n_vehicles * avg_kwh_per_vehicle
        kw_per_hour_total = total_kwh_per_day / max(1, n_window)
        # Normalizar contra UN cargador (el solver replica este perfil
        # tantas veces como cargadores tengan rated_kw_per_charger)
        normalized = min(1.0, kw_per_hour_total / (n_vehicles * rated_kw_per_charger))

        result = []
        for day in range(DAYS_PER_YEAR):
            day_of_week = day % 7
            # Sábados 50%, domingos 30%
            day_factor = (1.0 if day_of_week < 5
                          else 0.5 if day_of_week == 5 else 0.3)
            day_profile = [0.0] * HOURS_PER_DAY
            # Escalonamiento simple: rampa al inicio, plateau, rampa al final
            for i, h in enumerate(window_hours):
                # Posición relativa en la ventana [0, 1]
                rel = (i + 0.5) / n_window
                # Ramp-up suave en primer 20%, plateau, ramp-down ultimo 20%
                if rel < 0.2:
                    shape = rel / 0.2
                elif rel > 0.8:
                    shape = (1.0 - rel) / 0.2
                else:
                    shape = 1.0
                noise = 1.0 + self._rng.gauss(0, noise_pct)
                day_profile[h] = max(
                    0.0, min(1.0, normalized * day_factor * shape * noise)
                )
            result.extend(day_profile)
        return result


# =============================================================================
# LIBRERÍA DE PERFILES PRECONFIGURADOS
# =============================================================================
class ProfileLibrary:
    """
    Catálogo de perfiles 8760h listos para usar.

    Uso:
        lib = ProfileLibrary.ecuador_default()
        residential = lib["residential_sierra"]
        pv = lib["pv_sierra"]
    """

    @classmethod
    def ecuador_default(cls, seed: int = 42) -> Dict[str, List[float]]:
        """Set completo de perfiles para una distribuidora típica de Ecuador."""
        gen = ProfileGenerator(seed=seed)
        return {
            "residential_sierra":  gen.residential_sierra(),
            "residential_costa":   gen.residential_costa(),
            "commercial":          gen.commercial(),
            "industrial_24h":      gen.industrial(shift_hours=24),
            "industrial_8h":       gen.industrial(shift_hours=8),
            "street_lighting":     gen.street_lighting(),
            "pv_sierra":           gen.solar_pv(latitude_deg=-2.0,
                                                cloud_factor_mean=0.85),
            "pv_costa":            gen.solar_pv(latitude_deg=-2.2,
                                                cloud_factor_mean=0.80),
            "pv_oriente":          gen.solar_pv(latitude_deg=-1.5,
                                                cloud_factor_mean=0.65,
                                                cloud_factor_std=0.25),
            "ev_residential":      gen.ev_residential(),
            "ev_dc_fast":          gen.ev_dc_fast_public(),
            "ev_taxi":             gen.ev_taxi(),
            "ev_bus":              gen.ev_bus(),
            "ev_fleet_depot":      gen.ev_fleet_depot(),
        }

    @classmethod
    def from_csv(cls, path: str) -> Dict[str, List[float]]:
        """Carga perfiles desde un CSV con encabezado de nombres."""
        import csv
        profiles: Dict[str, List[float]] = {}
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for col in reader.fieldnames or []:
                profiles[col] = []
            for row in reader:
                for col, val in row.items():
                    if col is None:
                        continue
                    try:
                        profiles[col].append(float(val))
                    except (TypeError, ValueError):
                        profiles[col].append(0.0)
        # Validar que todos tengan 8760 entradas
        for k, v in profiles.items():
            if len(v) != HOURS_PER_YEAR:
                raise ValueError(
                    f"Perfil '{k}' tiene {len(v)} entradas, "
                    f"se esperaban {HOURS_PER_YEAR}."
                )
        return profiles


# =============================================================================
# Utilidades
# =============================================================================
def annual_energy_kwh(profile: List[float], rated_kw: float) -> float:
    """Energía total anual (kWh) consumida/generada con este perfil."""
    return sum(profile) * rated_kw


def peak_demand_kw(profile: List[float], rated_kw: float) -> float:
    """Demanda pico (kW)."""
    return max(profile) * rated_kw


def load_factor(profile: List[float]) -> float:
    """Factor de carga: promedio / pico."""
    if not profile:
        return 0.0
    avg = sum(profile) / len(profile)
    pk = max(profile)
    return avg / pk if pk > 0 else 0.0
