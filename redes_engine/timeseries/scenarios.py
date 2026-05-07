# -*- coding: utf-8 -*-
"""
redes_engine.timeseries.scenarios
==================================

Definición de escenarios futuros para análisis multianual.

Un escenario describe:
    - Año objetivo
    - Penetración de VE (% de hogares con vehículo eléctrico)
    - Penetración de PV (% de hogares con solar)
    - Despliegue de BESS (kWh totales nuevos)
    - Crecimiento de demanda base (%/año)
    - Tarifa de energía proyectada
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from .aggregator import AnnualResults


# =============================================================================
# Escenario individual
# =============================================================================
@dataclass
class Scenario:
    """
    Escenario futuro para análisis 8760h.

    Attributes
    ----------
    name : str
        Identificador legible.
    year : int
        Año objetivo (2030, 2050, etc.).
    ev_penetration_pct : float
        % de medidores residenciales con cargador VE.
    ev_avg_kwh_per_day : float
        Consumo promedio diario por VE (kWh).
    pv_penetration_pct : float
        % de medidores residenciales con PV.
    pv_avg_kwp : float
        Capacidad promedio instalada por sistema PV (kWp).
    bess_grid_capacity_kwh : float
        Capacidad total de BESS grid-scale añadida (kWh).
    bess_grid_power_kw : float
        Potencia total BESS grid-scale (kW).
    base_load_growth_pct_per_year : float
        Crecimiento anual de demanda base (típicamente 2-4%).
    base_year : int
        Año de referencia para escalar el crecimiento.
    """
    name: str
    year: int
    ev_penetration_pct: float = 0.0
    ev_avg_kwh_per_day: float = 22.0
    pv_penetration_pct: float = 0.0
    pv_avg_kwp: float = 5.0
    bess_grid_capacity_kwh: float = 0.0
    bess_grid_power_kw: float = 0.0
    base_load_growth_pct_per_year: float = 3.0
    base_year: int = 2026
    notes: str = ""

    @property
    def years_from_base(self) -> int:
        return max(0, self.year - self.base_year)

    @property
    def base_load_factor(self) -> float:
        """
        Factor multiplicativo de la demanda base por crecimiento compuesto.
        Ejemplo: 3%/año durante 4 años → 1.03^4 = 1.1255 (12.55% más demanda).
        """
        rate = self.base_load_growth_pct_per_year / 100.0
        return (1.0 + rate) ** self.years_from_base

    # =========================================================================
    # Aplicación del escenario a una red existente
    # =========================================================================
    def apply_to_network(
        self,
        network,
        profiles: Dict[str, List[float]],
        random_seed: int = 42,
    ) -> "ScenarioApplication":
        """
        Aplica el escenario a un Network existente:
            - Escala las cargas existentes por el factor de crecimiento
            - Sintetiza VE en una fracción de los medidores residenciales
            - Sintetiza PV en una fracción de los medidores residenciales
            - Añade BESS grid-scale al bus con mayor demanda

        Returns
        -------
        ScenarioApplication : objeto que describe los cambios y los perfiles
                              asignados a cada asset.
        """
        import random

        rng = random.Random(random_seed)

        # Importar tipos del paquete principal (evita import circular en module-load)
        from ..core.graph import Asset, AssetType
        from ..core.network import Network as NetType  # solo para anotar

        application = ScenarioApplication(scenario=self)

        # 1. Identificar medidores residenciales existentes
        residential_assets = [
            a for a in network.assets.values()
            if a.asset_type == AssetType.LOAD_RESIDENCIAL
        ]
        n_resid = len(residential_assets)

        # 2. Escalar cargas existentes por crecimiento de demanda
        growth = self.base_load_factor
        for asset in network.assets.values():
            if asset.is_load() and not asset.is_ev():
                asset.rated_kw *= growth
                application.scaled_loads.append((asset.id, growth))

        # 3. Determinar cuántos VE y PV añadir
        n_ev = int(round(n_resid * self.ev_penetration_pct / 100.0))
        n_pv = int(round(n_resid * self.pv_penetration_pct / 100.0))

        # 4. Asignar VE aleatoriamente a medidores
        ev_targets = rng.sample(residential_assets, min(n_ev, n_resid))
        ev_kw_rated = self.ev_avg_kwh_per_day / 4.0   # ~4 horas de carga
        for ld in ev_targets:
            ev_id = f"EV_{ld.bus_id}_synth"
            if ev_id in network.assets:
                continue
            ev = Asset(
                id=ev_id, bus_id=ld.bus_id,
                asset_type=AssetType.EV_CHARGER_AC_L2,
                rated_kw=max(3.7, ev_kw_rated),
                controllable=True,
                profile_24h_kw=None,   # se asigna perfil 8760h aparte
            )
            network.add_asset(ev)
            application.added_evs.append(ev_id)

        # 5. Asignar PV
        pv_targets = rng.sample(residential_assets, min(n_pv, n_resid))
        for ld in pv_targets:
            pv_id = f"PV_{ld.bus_id}_synth"
            if pv_id in network.assets:
                continue
            pv = Asset(
                id=pv_id, bus_id=ld.bus_id,
                asset_type=AssetType.SOLAR_PV_RESID,
                rated_kw=self.pv_avg_kwp,
                capacity_factor=0.18,
            )
            network.add_asset(pv)
            application.added_pvs.append(pv_id)

        # 6. BESS grid-scale (si aplica) en el bus con mayor demanda
        if self.bess_grid_capacity_kwh > 0 and self.bess_grid_power_kw > 0:
            # Bus con más cargas asignadas
            bus_demand: Dict[str, float] = {}
            for a in network.assets.values():
                if a.is_load():
                    bus_demand[a.bus_id] = bus_demand.get(a.bus_id, 0.0) + a.rated_kw
            if bus_demand:
                target_bus = max(bus_demand, key=bus_demand.get)
                bess_id = f"BESS_grid_{self.year}"
                if bess_id not in network.assets:
                    bess = Asset(
                        id=bess_id, bus_id=target_bus,
                        asset_type=AssetType.BESS_GRID_SCALE,
                        rated_kw=self.bess_grid_power_kw,
                        capacity_kwh=self.bess_grid_capacity_kwh,
                        controllable=True, bidirectional=True,
                    )
                    network.add_asset(bess)
                    application.added_bess.append(bess_id)

        return application


# =============================================================================
# Resultado de la aplicación de un escenario
# =============================================================================
@dataclass
class ScenarioApplication:
    """Reporte de los cambios que el escenario aplicó a la red."""
    scenario: Scenario
    scaled_loads: List = field(default_factory=list)
    added_evs: List[str] = field(default_factory=list)
    added_pvs: List[str] = field(default_factory=list)
    added_bess: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "═" * 60,
            f"  ESCENARIO: {self.scenario.name}  (año {self.scenario.year})",
            "═" * 60,
            f"  Crecimiento de demanda     : "
            f"+{(self.scenario.base_load_factor-1)*100:.1f}%",
            f"  Cargas escaladas           : {len(self.scaled_loads)}",
            f"  Cargadores VE añadidos     : {len(self.added_evs)} "
            f"({self.scenario.ev_penetration_pct:.1f}% penetración)",
            f"  Sistemas PV añadidos       : {len(self.added_pvs)} "
            f"({self.scenario.pv_penetration_pct:.1f}% penetración)",
            f"  BESS grid-scale añadidos   : {len(self.added_bess)} "
            f"({self.scenario.bess_grid_capacity_kwh:.0f} kWh)",
            "═" * 60,
        ]
        return "\n".join(lines)


# =============================================================================
# Comparación de múltiples escenarios
# =============================================================================
@dataclass
class ScenarioComparison:
    """
    Compara métricas anuales entre múltiples escenarios.

    Uso típico:
        cmp = ScenarioComparison()
        cmp.add(scenario_2026, annual_results_2026)
        cmp.add(scenario_2030, annual_results_2030)
        print(cmp.diff_table())
    """
    scenarios: Dict[str, "AnnualResults"] = field(default_factory=dict)

    def add(self, scenario: Scenario, results) -> None:
        self.scenarios[scenario.name] = results

    def diff_table(self) -> str:
        if not self.scenarios:
            return "(sin escenarios)"
        names = list(self.scenarios.keys())
        rows = []
        rows.append(f"{'Métrica':<35}" + "".join(f"{n:>14}" for n in names))
        rows.append("─" * (35 + 14 * len(names)))

        metrics = [
            ("Energía servida (MWh/año)",
             lambda r: r.total_energy_served_mwh),
            ("Pérdidas técnicas (MWh)",
             lambda r: r.total_losses_mwh),
            ("Pérdidas técnicas (%)",
             lambda r: r.losses_pct),
            ("Demanda pico (kW)",
             lambda r: r.peak_demand_kw),
            ("Pico de pérdidas (kW)",
             lambda r: r.peak_losses_kw),
            ("Buses en violación (al menos 1h)",
             lambda r: len(r.buses_with_violation_hours)),
            ("Branches sobrecargados",
             lambda r: len(r.branches_with_overload_hours)),
            ("Hora-trafo más cargada (%)",
             lambda r: r.peak_transformer_loading_pct),
        ]

        for label, getter in metrics:
            values = []
            for name in names:
                try:
                    v = getter(self.scenarios[name])
                    values.append(f"{v:>14.2f}" if isinstance(v, (int, float))
                                  else f"{str(v):>14}")
                except Exception:
                    values.append(f"{'?':>14}")
            rows.append(f"{label:<35}" + "".join(values))
        return "\n".join(rows)
