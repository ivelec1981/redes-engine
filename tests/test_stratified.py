# -*- coding: utf-8 -*-
"""
Tests del muestreo estratificado de VE/PV.

Verifican:
    - El muestreo respeta los pesos por estrato (estratos altos seleccionados
      con mayor frecuencia para VE).
    - Tamaño individual VE/PV varía con el estrato.
    - Asset.socioeconomic_stratum se persiste vía .rsproj.
    - Cuando use_socioeconomic_strata=False, comportamiento legacy uniforme.
"""

import os
import random
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.core.graph import (
    Asset, AssetType, Bus, BusType, VoltageLevel,
)
from redes_engine.core.network import Network
from redes_engine.timeseries import (
    EV_ADOPTION_WEIGHTS,
    PV_ADOPTION_WEIGHTS,
    Scenario,
    expected_ev_kwh_per_day_for,
    expected_kwp_for,
    stratified_sample,
    stratum_distribution,
)


# =============================================================================
# Fixtures
# =============================================================================
def _make_residential(n_per_stratum: dict, has_roof_per_stratum: dict = None):
    """Crea una lista de Assets residenciales con estratos asignados."""
    has_roof_per_stratum = has_roof_per_stratum or {}
    assets = []
    counter = 0
    for stratum, n in n_per_stratum.items():
        for i in range(n):
            counter += 1
            assets.append(Asset(
                id=f"L_{stratum}_{i}",
                bus_id=f"BUS_{counter}",
                asset_type=AssetType.LOAD_RESIDENCIAL,
                rated_kw=2.0,
                socioeconomic_stratum=stratum,
                has_roof_pv_potential=has_roof_per_stratum.get(stratum, True),
            ))
    return assets


# =============================================================================
# stratified_sample — pesos
# =============================================================================
class TestStratifiedSample:

    def test_high_stratum_selected_more_often_for_ev(self):
        """Con peso fuerte hacia estratos altos, deben dominar la muestra."""
        # 50 hogares por estrato (1..5), elegir 50 (la mitad del pool)
        residential = _make_residential({1: 50, 2: 50, 3: 50, 4: 50, 5: 50})

        # Repetir muchas veces para promediar
        counts_high = 0  # estratos 4 + 5
        counts_low = 0   # estratos 1 + 2
        N_RUNS = 30
        for seed in range(N_RUNS):
            rng = random.Random(seed)
            picked = stratified_sample(
                residential, 50, EV_ADOPTION_WEIGHTS, rng,
            )
            for a in picked:
                if a.socioeconomic_stratum >= 4:
                    counts_high += 1
                elif a.socioeconomic_stratum <= 2:
                    counts_low += 1

        # Estratos altos deben elegirse mucho más que los bajos
        assert counts_high > 5 * counts_low, (
            f"Esperaba dominio claro de estratos altos. "
            f"high={counts_high}, low={counts_low}"
        )

    def test_size_truncated_to_pool(self):
        """Si n_to_select > pool, devuelve todos."""
        residential = _make_residential({3: 5})
        rng = random.Random(0)
        picked = stratified_sample(residential, 100, EV_ADOPTION_WEIGHTS, rng)
        assert len(picked) == 5

    def test_zero_returns_empty(self):
        residential = _make_residential({3: 10})
        rng = random.Random(0)
        assert stratified_sample(residential, 0, EV_ADOPTION_WEIGHTS, rng) == []

    def test_no_stratum_uses_default(self):
        """Assets sin estrato siguen siendo seleccionables."""
        residential = [Asset(
            id=f"L_{i}", bus_id=f"B_{i}",
            asset_type=AssetType.LOAD_RESIDENCIAL, rated_kw=2.0,
        ) for i in range(20)]
        rng = random.Random(0)
        picked = stratified_sample(residential, 5, EV_ADOPTION_WEIGHTS, rng)
        assert len(picked) == 5

    def test_pv_filter_by_roof_potential(self):
        """PV exige has_roof_pv_potential=True (None se acepta)."""
        with_roof = _make_residential(
            {3: 10}, has_roof_per_stratum={3: True},
        )
        without_roof = _make_residential(
            {3: 10}, has_roof_per_stratum={3: False},
        )
        rng = random.Random(0)
        picked = stratified_sample(
            with_roof + without_roof, 10, PV_ADOPTION_WEIGHTS, rng,
            require_attribute="has_roof_pv_potential",
        )
        assert len(picked) == 10
        for a in picked:
            assert a.has_roof_pv_potential is True


# =============================================================================
# Tamaños por estrato
# =============================================================================
class TestStratifiedSizing:

    def test_pv_kwp_increases_with_high_stratum(self):
        a_low = Asset(
            id="L1", bus_id="B1", asset_type=AssetType.LOAD_RESIDENCIAL,
            rated_kw=1.5, socioeconomic_stratum=1,
        )
        a_high = Asset(
            id="L2", bus_id="B2", asset_type=AssetType.LOAD_RESIDENCIAL,
            rated_kw=4.0, socioeconomic_stratum=5,
        )
        assert expected_kwp_for(a_high) > expected_kwp_for(a_low)

    def test_ev_kwh_increases_with_high_stratum(self):
        a_low = Asset(
            id="L1", bus_id="B1", asset_type=AssetType.LOAD_RESIDENCIAL,
            rated_kw=1.5, socioeconomic_stratum=1,
        )
        a_high = Asset(
            id="L2", bus_id="B2", asset_type=AssetType.LOAD_RESIDENCIAL,
            rated_kw=4.0, socioeconomic_stratum=5,
        )
        assert expected_ev_kwh_per_day_for(a_high) > expected_ev_kwh_per_day_for(a_low)

    def test_default_used_when_no_stratum(self):
        a = Asset(
            id="L", bus_id="B", asset_type=AssetType.LOAD_RESIDENCIAL,
            rated_kw=2.0,
        )
        assert expected_kwp_for(a, default_kwp=5.0) == 5.0
        assert expected_ev_kwh_per_day_for(a, default_kwh=22.0) == 22.0


# =============================================================================
# Distribución de estratos
# =============================================================================
class TestDistribution:

    def test_stratum_distribution_counts(self):
        residential = _make_residential({1: 3, 3: 7, 5: 2})
        d = stratum_distribution(residential)
        assert d == {1: 3, 3: 7, 5: 2}

    def test_distribution_includes_none(self):
        a1 = Asset(id="L1", bus_id="B1",
                   asset_type=AssetType.LOAD_RESIDENCIAL, rated_kw=2.0,
                   socioeconomic_stratum=3)
        a2 = Asset(id="L2", bus_id="B2",
                   asset_type=AssetType.LOAD_RESIDENCIAL, rated_kw=2.0)
        d = stratum_distribution([a1, a2])
        assert d == {3: 1, None: 1}


# =============================================================================
# Integración con Scenario.apply_to_network
# =============================================================================
class TestScenarioIntegration:

    @pytest.fixture
    def small_network(self):
        net = Network(name="estratos_demo")
        # 1 fuente + 20 medidores residenciales mezcla de estratos
        net.add_bus(Bus(
            id="SRC", geometry=(0, 0), voltage_kv=22.8,
            level=VoltageLevel.MT_22_8KV, bus_type=BusType.BARRA_SE,
        ))
        # 4 estrato 5 (alto), 8 estrato 3, 8 estrato 1 (bajo)
        for stratum, n in [(5, 4), (3, 8), (1, 8)]:
            for i in range(n):
                bus_id = f"B_{stratum}_{i}"
                net.add_bus(Bus(
                    id=bus_id, geometry=(i, stratum),
                    voltage_kv=0.22, level=VoltageLevel.BT_220_127,
                    bus_type=BusType.MEDIDOR,
                ))
                net.add_asset(Asset(
                    id=f"L_{stratum}_{i}", bus_id=bus_id,
                    asset_type=AssetType.LOAD_RESIDENCIAL, rated_kw=2.0,
                    socioeconomic_stratum=stratum,
                    has_roof_pv_potential=True,
                ))
        return net

    def test_stratified_scenario_prefers_high_strata(self, small_network):
        # 50% penetración VE → debe favorecer estratos altos
        sc = Scenario(
            name="EV50", year=2030,
            ev_penetration_pct=50.0,
            use_socioeconomic_strata=True,
        )
        app = sc.apply_to_network(small_network, profiles={}, random_seed=7)
        assert len(app.added_evs) == 10   # 50% × 20

        # Ver qué estratos quedaron con VE
        ev_strata = []
        for ev_id in app.added_evs:
            ev = small_network.assets[ev_id]
            ev_strata.append(ev.socioeconomic_stratum)
        c = Counter(ev_strata)
        # Estrato 5 (alto, 4 hogares) debe estar prácticamente todo cubierto
        assert c.get(5, 0) >= 3
        # Estrato 1 (bajo) debe tener pocos VE — peso 0.01 es 100× menor que 1.0
        assert c.get(1, 0) <= 2

    def test_ev_size_reflects_stratum(self, small_network):
        sc = Scenario(
            name="EV", year=2030,
            ev_penetration_pct=100.0,
            use_socioeconomic_strata=True,
            use_stratified_sizing=True,
        )
        sc.apply_to_network(small_network, profiles={}, random_seed=0)
        # Encontrar VE en estrato 5 vs estrato 1
        ev_5 = next(
            (a for a in small_network.assets.values()
             if a.is_ev() and a.socioeconomic_stratum == 5),
            None,
        )
        ev_1 = next(
            (a for a in small_network.assets.values()
             if a.is_ev() and a.socioeconomic_stratum == 1),
            None,
        )
        assert ev_5 is not None and ev_1 is not None
        # Estrato 5 debe tener mayor potencia que estrato 1
        assert ev_5.rated_kw > ev_1.rated_kw

    def test_uniform_mode_does_not_correlate_with_stratum(self, small_network):
        """En modo legacy, la selección VE no debe correlacionar con estrato."""
        sc = Scenario(
            name="EV", year=2030,
            ev_penetration_pct=50.0,
            use_socioeconomic_strata=False,   # legacy
        )
        app = sc.apply_to_network(small_network, profiles={}, random_seed=42)
        # Debería elegir aproximadamente 10 medidores; no debe priorizar uno
        # u otro estrato (sólo verificamos que se eligen).
        assert len(app.added_evs) == 10


# =============================================================================
# Persistencia .rsproj con estratos
# =============================================================================
class TestStratumPersistence:

    def test_socioeconomic_stratum_round_trips(self, tmp_path):
        from redes_engine.persistence import (
            RSProjectContainer, load_container, save_container,
        )

        net = Network(name="strat_test")
        net.add_bus(Bus(
            id="B1", geometry=(0, 0), voltage_kv=0.22,
            level=VoltageLevel.BT_220_127, bus_type=BusType.MEDIDOR,
        ))
        net.add_asset(Asset(
            id="L1", bus_id="B1",
            asset_type=AssetType.LOAD_RESIDENCIAL, rated_kw=2.0,
            socioeconomic_stratum=4,
            has_roof_pv_potential=True,
            roof_area_m2=85.5,
        ))

        path = tmp_path / "strat.rsproj"
        c = RSProjectContainer.from_network(net)
        save_container(c, str(path))
        loaded = load_container(str(path))
        a = loaded.network.assets["L1"]
        assert a.socioeconomic_stratum == 4
        assert a.has_roof_pv_potential is True
        assert a.roof_area_m2 == 85.5
