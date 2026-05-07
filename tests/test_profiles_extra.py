# -*- coding: utf-8 -*-
"""Tests de los nuevos perfiles taxi/bus/flota (G4)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.timeseries import HOURS_PER_YEAR, ProfileGenerator, ProfileLibrary


class TestNewVehicleProfiles:

    def test_taxi_profile_has_8760(self):
        gen = ProfileGenerator(seed=1)
        p = gen.ev_taxi()
        assert len(p) == HOURS_PER_YEAR

    def test_taxi_charges_mostly_at_night(self):
        gen = ProfileGenerator(seed=42)
        p = gen.ev_taxi()
        # Sumar primeras 30 días por hora
        sums = [0.0] * 24
        for d in range(30):
            for h in range(24):
                sums[h] += p[d * 24 + h]
        # Energía nocturna (1-6h) > resto del día
        night = sum(sums[1:7])
        day = sum(sums[7:24]) + sums[0]
        assert night > day * 0.4   # al menos 40% en madrugada

    def test_bus_profile_charges_at_depot_window(self):
        gen = ProfileGenerator(seed=1)
        p = gen.ev_bus(depot_window=(23, 5))
        # Para los primeros 7 días, el cargador del bus solo opera 23h-5h
        # En horas 6-22 debe estar idle
        for d in range(5):  # solo días laborales
            for h in range(8, 18):
                assert p[d * 24 + h] == pytest.approx(0.0, abs=1e-6)

    def test_fleet_depot_zero_during_business_hours(self):
        gen = ProfileGenerator(seed=1)
        p = gen.ev_fleet_depot(arrival_hour=18, departure_hour=6)
        # En medio del día (10-15h) debe estar idle
        for d in range(5):
            for h in range(10, 15):
                assert p[d * 24 + h] == pytest.approx(0.0, abs=1e-6)

    def test_library_includes_all_new_profiles(self):
        lib = ProfileLibrary.ecuador_default()
        for name in ("ev_taxi", "ev_bus", "ev_fleet_depot"):
            assert name in lib
            assert len(lib[name]) == HOURS_PER_YEAR
