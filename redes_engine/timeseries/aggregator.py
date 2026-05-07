# -*- coding: utf-8 -*-
"""
redes_engine.timeseries.aggregator
====================================

Estadísticas anuales agregadas a partir de 8760 resultados horarios.

Convertimos las series temporales en métricas accionables:
    - Picos (demanda, voltaje, carga, pérdidas)
    - Horas en violación
    - Energía total (servida, pérdidas, exportada)
    - Worst-case bus / branch
"""

from dataclasses import dataclass, field
from typing import Dict, List


# =============================================================================
# Estadísticas por bus
# =============================================================================
@dataclass
class BusAnnualStats:
    """Resumen anual de un bus."""
    bus_id: str
    voltage_nominal_kv: float
    v_pu_min: float = 1.0
    v_pu_max: float = 1.0
    v_drop_max_pct: float = 0.0
    hours_in_violation: int = 0
    hours_in_warning: int = 0
    worst_hour: int = 0    # hora del año donde ocurre v_drop_max

    def violation_pct(self) -> float:
        return 100.0 * self.hours_in_violation / 8760.0


# =============================================================================
# Estadísticas por branch
# =============================================================================
@dataclass
class BranchAnnualStats:
    """Resumen anual de un branch (línea o trafo)."""
    branch_id: str
    rated_a: float = 0.0
    loading_max_pct: float = 0.0
    loading_avg_pct: float = 0.0
    hours_overloaded: int = 0
    hours_warning: int = 0
    energy_through_kwh: float = 0.0
    energy_losses_kwh: float = 0.0
    worst_hour: int = 0

    def overload_pct(self) -> float:
        return 100.0 * self.hours_overloaded / 8760.0


# =============================================================================
# Resultado anual completo
# =============================================================================
@dataclass
class AnnualResults:
    """
    Resultados consolidados de un año completo (8760 horas).
    """
    scenario_name: str = ""
    n_hours_simulated: int = 0
    n_hours_failed: int = 0

    # Energía
    total_energy_served_mwh: float = 0.0
    total_energy_imported_mwh: float = 0.0
    total_energy_exported_mwh: float = 0.0
    total_losses_mwh: float = 0.0
    losses_pct: float = 0.0

    # Demanda
    peak_demand_kw: float = 0.0
    peak_demand_hour: int = 0
    avg_demand_kw: float = 0.0
    load_factor: float = 0.0

    # Pérdidas
    peak_losses_kw: float = 0.0
    avg_losses_kw: float = 0.0

    # Estadísticas por bus / branch
    bus_stats: Dict[str, BusAnnualStats] = field(default_factory=dict)
    branch_stats: Dict[str, BranchAnnualStats] = field(default_factory=dict)

    # Trafo crítico
    peak_transformer_loading_pct: float = 0.0
    peak_transformer_id: str = ""

    # =========================================================================
    # Análisis derivado
    # =========================================================================
    @property
    def buses_with_violation_hours(self) -> List[BusAnnualStats]:
        return [b for b in self.bus_stats.values() if b.hours_in_violation > 0]

    @property
    def buses_with_warning_hours(self) -> List[BusAnnualStats]:
        return [b for b in self.bus_stats.values() if b.hours_in_warning > 0]

    @property
    def branches_with_overload_hours(self) -> List[BranchAnnualStats]:
        return [b for b in self.branch_stats.values() if b.hours_overloaded > 0]

    def worst_voltage_bus(self) -> "BusAnnualStats | None":
        if not self.bus_stats:
            return None
        return max(self.bus_stats.values(), key=lambda b: abs(b.v_drop_max_pct))

    def most_loaded_branch(self) -> "BranchAnnualStats | None":
        if not self.branch_stats:
            return None
        return max(self.branch_stats.values(), key=lambda b: b.loading_max_pct)

    # =========================================================================
    # Reportes
    # =========================================================================
    def summary(self) -> str:
        lines = [
            "═" * 64,
            f"  RESULTADOS ANUALES — {self.scenario_name}",
            "═" * 64,
            f"  Horas simuladas              : {self.n_hours_simulated} / 8760",
            f"  Horas con fallo de convergencia: {self.n_hours_failed}",
            "─" * 64,
            f"  Energía servida              : {self.total_energy_served_mwh:>10,.2f} MWh",
            f"  Energía importada            : {self.total_energy_imported_mwh:>10,.2f} MWh",
            f"  Energía exportada (PV→red)   : {self.total_energy_exported_mwh:>10,.2f} MWh",
            f"  Pérdidas técnicas            : {self.total_losses_mwh:>10,.2f} MWh "
            f"({self.losses_pct:.2f}%)",
            "─" * 64,
            f"  Demanda pico                 : {self.peak_demand_kw:>10,.2f} kW "
            f"(hora {self.peak_demand_hour})",
            f"  Demanda promedio             : {self.avg_demand_kw:>10,.2f} kW",
            f"  Factor de carga              : {self.load_factor:>10.3f}",
            f"  Pérdidas pico                : {self.peak_losses_kw:>10,.2f} kW",
            "─" * 64,
            f"  Buses en violación (≥1h/año) : {len(self.buses_with_violation_hours)}",
            f"  Buses en advertencia         : {len(self.buses_with_warning_hours)}",
            f"  Branches sobrecargados       : {len(self.branches_with_overload_hours)}",
        ]

        worst = self.worst_voltage_bus()
        if worst:
            lines.append(
                f"  Peor caída de voltaje        : {worst.bus_id} "
                f"= {worst.v_drop_max_pct:+.2f}% en hora {worst.worst_hour}"
            )

        loaded = self.most_loaded_branch()
        if loaded:
            lines.append(
                f"  Branch más cargado           : {loaded.branch_id} "
                f"= {loaded.loading_max_pct:.1f}% en hora {loaded.worst_hour}"
            )

        if self.peak_transformer_id:
            lines.append(
                f"  Trafo más cargado            : {self.peak_transformer_id} "
                f"@ {self.peak_transformer_loading_pct:.1f}%"
            )
        lines.append("═" * 64)
        return "\n".join(lines)

    def violation_table(self, max_rows: int = 10) -> str:
        """Tabla de buses con más horas de violación."""
        sorted_buses = sorted(
            self.bus_stats.values(),
            key=lambda b: -b.hours_in_violation,
        )[:max_rows]

        lines = [
            "",
            f"  TOP {max_rows} BUSES CON VIOLACIONES DE VOLTAJE (8760h)",
            "  " + "─" * 60,
            f"  {'Bus':<18} {'Vmin':>7} {'Vmax':>7} {'ΔV max%':>10} "
            f"{'Hrs viol':>10} {'%/año':>7}",
            "  " + "─" * 60,
        ]
        for b in sorted_buses:
            if b.hours_in_violation == 0:
                continue
            lines.append(
                f"  {b.bus_id:<18} "
                f"{b.v_pu_min:>7.4f} {b.v_pu_max:>7.4f} "
                f"{b.v_drop_max_pct:>+9.2f}% "
                f"{b.hours_in_violation:>10} "
                f"{b.violation_pct():>6.1f}%"
            )
        return "\n".join(lines)

    def overload_table(self, max_rows: int = 10) -> str:
        """Tabla de branches con más horas sobrecargados."""
        sorted_branches = sorted(
            self.branch_stats.values(),
            key=lambda b: -b.hours_overloaded,
        )[:max_rows]

        lines = [
            "",
            f"  TOP {max_rows} BRANCHES SOBRECARGADOS (8760h)",
            "  " + "─" * 60,
            f"  {'Branch':<14} {'Pico%':>8} {'Avg%':>8} "
            f"{'Hrs >100%':>10} {'Energía MWh':>12}",
            "  " + "─" * 60,
        ]
        for b in sorted_branches:
            lines.append(
                f"  {b.branch_id:<14} "
                f"{b.loading_max_pct:>8.1f} "
                f"{b.loading_avg_pct:>8.1f} "
                f"{b.hours_overloaded:>10} "
                f"{b.energy_through_kwh / 1000:>12.2f}"
            )
        return "\n".join(lines)


# =============================================================================
# Acumulador interno (durante la simulación 8760h)
# =============================================================================
class AnnualAggregator:
    """
    Acumula estadísticas hora-a-hora durante la simulación, sin guardar
    todos los 8760 resultados en memoria. Solo extrae lo accionable.
    """

    def __init__(self, voltage_violation_pct: float = 5.0):
        self.bus_stats: Dict[str, BusAnnualStats] = {}
        self.branch_stats: Dict[str, BranchAnnualStats] = {}
        self.voltage_violation_pct = voltage_violation_pct

        # Acumuladores globales
        self.energy_served_kwh = 0.0
        self.energy_losses_kwh = 0.0
        self.energy_imported_kwh = 0.0
        self.energy_exported_kwh = 0.0

        self.peak_demand_kw = 0.0
        self.peak_demand_hour = 0
        self.peak_losses_kw = 0.0
        self.demand_sum = 0.0
        self.losses_sum = 0.0
        self.n_hours = 0

        self.peak_transformer_id = ""
        self.peak_transformer_loading_pct = 0.0

    def update(self, hour: int, hourly_result) -> None:
        """Añade un resultado horario al acumulador."""
        self.n_hours += 1
        # Energía/potencia globales
        p_kw = hourly_result.total_power_kw
        losses_kw = hourly_result.total_losses_kw

        self.energy_served_kwh += p_kw
        self.energy_losses_kwh += losses_kw
        self.energy_imported_kwh += max(p_kw, 0)
        self.energy_exported_kwh += max(-p_kw, 0)

        self.demand_sum += p_kw
        self.losses_sum += losses_kw

        if p_kw > self.peak_demand_kw:
            self.peak_demand_kw = p_kw
            self.peak_demand_hour = hour
        if losses_kw > self.peak_losses_kw:
            self.peak_losses_kw = losses_kw

        # Estadísticas por bus
        from ..core.results import ComplianceStatus
        for bus_id, v in hourly_result.bus_voltages.items():
            stats = self.bus_stats.get(bus_id)
            if stats is None:
                stats = BusAnnualStats(
                    bus_id=bus_id,
                    voltage_nominal_kv=v.voltage_nominal_kv,
                    v_pu_min=v.v_pu, v_pu_max=v.v_pu,
                )
                self.bus_stats[bus_id] = stats
            stats.v_pu_min = min(stats.v_pu_min, v.v_pu)
            stats.v_pu_max = max(stats.v_pu_max, v.v_pu)
            if abs(v.v_drop_pct) > abs(stats.v_drop_max_pct):
                stats.v_drop_max_pct = v.v_drop_pct
                stats.worst_hour = hour
            if v.compliance == ComplianceStatus.VIOLATION:
                stats.hours_in_violation += 1
            elif v.compliance == ComplianceStatus.WARNING:
                stats.hours_in_warning += 1

        # Estadísticas por branch
        for branch_id, b in hourly_result.branch_flows.items():
            stats = self.branch_stats.get(branch_id)
            if stats is None:
                stats = BranchAnnualStats(
                    branch_id=branch_id, rated_a=b.rated_a,
                    loading_max_pct=b.loading_pct,
                    loading_avg_pct=b.loading_pct,
                )
                self.branch_stats[branch_id] = stats

            stats.loading_avg_pct = (
                (stats.loading_avg_pct * (self.n_hours - 1) + b.loading_pct)
                / self.n_hours
            )
            if b.loading_pct > stats.loading_max_pct:
                stats.loading_max_pct = b.loading_pct
                stats.worst_hour = hour
                # Trafo más cargado
                if "T" in branch_id.upper() and b.loading_pct > self.peak_transformer_loading_pct:
                    self.peak_transformer_loading_pct = b.loading_pct
                    self.peak_transformer_id = branch_id
            if b.loading_pct > 100.0:
                stats.hours_overloaded += 1
            elif b.loading_pct > 80.0:
                stats.hours_warning += 1

            stats.energy_through_kwh += abs(b.p_kw)
            stats.energy_losses_kwh += b.losses_kw

    def finalize(self, scenario_name: str = "") -> AnnualResults:
        """Construye el AnnualResults final."""
        result = AnnualResults(
            scenario_name=scenario_name,
            n_hours_simulated=self.n_hours,
        )
        result.total_energy_served_mwh = self.energy_served_kwh / 1000.0
        result.total_energy_imported_mwh = self.energy_imported_kwh / 1000.0
        result.total_energy_exported_mwh = self.energy_exported_kwh / 1000.0
        result.total_losses_mwh = self.energy_losses_kwh / 1000.0
        if result.total_energy_served_mwh > 0:
            result.losses_pct = (
                100.0 * result.total_losses_mwh / result.total_energy_served_mwh
            )
        result.peak_demand_kw = self.peak_demand_kw
        result.peak_demand_hour = self.peak_demand_hour
        result.peak_losses_kw = self.peak_losses_kw
        if self.n_hours > 0:
            result.avg_demand_kw = self.demand_sum / self.n_hours
            result.avg_losses_kw = self.losses_sum / self.n_hours
            if result.peak_demand_kw > 0:
                result.load_factor = result.avg_demand_kw / result.peak_demand_kw

        result.bus_stats = self.bus_stats
        result.branch_stats = self.branch_stats
        result.peak_transformer_id = self.peak_transformer_id
        result.peak_transformer_loading_pct = self.peak_transformer_loading_pct

        return result
