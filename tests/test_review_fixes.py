# -*- coding: utf-8 -*-
"""
Tests de regresión para los fixes derivados de la revisión integral del proyecto.

Cubren:
    #4 — Numeración contigua de secciones del reporte (sin huecos 1→7→8).
    #5 — Energía exportada (PV→red) usando net_power_kw con signo.
    #3 — Protección anti zip-bomb / DoS al cargar un .rsproj.
    #2 — Restauración del estado de workflow (active_domains/emitted_docs)
         al recargar un .rsproj.
"""

import io
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest


# =============================================================================
# #4 — Numeración de secciones del reporte
# =============================================================================
class TestReportNumbering:

    def _numbered(self, sections):
        """Devuelve la lista de números de las secciones que empiezan con 'N.'."""
        nums = []
        for sec in sections:
            m = re.match(r"^(\d+)\.", sec.title)
            if m:
                nums.append(int(m.group(1)))
        return nums

    def test_contiguous_when_sections_skipped(self):
        from redes_engine.engineering import (
            InvestmentAnalyzer, InvestmentAssumptions,
        )
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        from redes_engine.reports import ReportBuilder, ReportContext

        inv = InvestmentAnalyzer(InvestmentAssumptions(horizon_years=5)).analyze(
            capex_direct_usd=120_000, annual_capacity_savings_usd=18_000,
        )
        # Contexto que OMITE solve/compliance/annual/hosting/bom:
        # antes producía "1. Descripción → 7. Inversión → 8. Recomendaciones".
        ctx = ReportContext(
            title="T", project_name="P",
            network=build_urbanizacion_pastaza(),
            investment_result=inv,
        )
        sections = ReportBuilder(ctx).build_all()
        nums = self._numbered(sections)
        # Deben ser contiguos 1..N sin huecos
        assert nums == list(range(1, len(nums) + 1)), (
            f"Numeración no contigua: {nums}"
        )
        # El resumen ejecutivo NO debe llevar número
        assert sections[0].title == "Resumen Ejecutivo"
        # La sección de inversión debe existir y estar numerada
        assert any("Inversión" in s.title and re.match(r"^\d+\.", s.title)
                   for s in sections)

    def test_recommendations_only_is_section_1(self):
        # Contexto mínimo (sin red): solo Resumen + Recomendaciones.
        # Recomendaciones debe quedar como "1." (no "8.").
        from redes_engine.reports import ReportBuilder, ReportContext

        ctx = ReportContext(title="T", project_name="P")
        sections = ReportBuilder(ctx).build_all()
        nums = self._numbered(sections)
        assert nums == list(range(1, len(nums) + 1))
        rec = next(s for s in sections if "Recomendaciones" in s.title)
        assert rec.title.startswith("1.")


# =============================================================================
# #5 — Energía exportada con net_power_kw
# =============================================================================
class TestExportEnergy:

    def test_export_accumulated_when_net_negative(self):
        from redes_engine.core.results import PowerFlowResult
        from redes_engine.timeseries.aggregator import AnnualAggregator

        agg = AnnualAggregator()
        # Hora 0: importa 100 kW (net +100)
        r_import = PowerFlowResult(
            converged=True, total_power_kw=100.0, net_power_kw=100.0,
            total_losses_kw=2.0,
        )
        # Hora 1: exporta 40 kW (net −40); total_power_kw es magnitud
        r_export = PowerFlowResult(
            converged=True, total_power_kw=40.0, net_power_kw=-40.0,
            total_losses_kw=1.0,
        )
        agg.update(0, r_import)
        agg.update(1, r_export)

        assert agg.energy_imported_kwh == pytest.approx(100.0)
        # ANTES del fix esto era 0.0 (bug: max(-abs,0))
        assert agg.energy_exported_kwh == pytest.approx(40.0)

    def test_fallback_to_magnitude_without_net_field(self):
        # Un resultado sin net_power_kw (p.ej. solver no temporal) no rompe.
        from redes_engine.core.results import PowerFlowResult
        from redes_engine.timeseries.aggregator import AnnualAggregator

        agg = AnnualAggregator()
        r = PowerFlowResult(converged=True, total_power_kw=50.0,
                            total_losses_kw=1.0)
        # net_power_kw default 0.0 → getattr lo toma; import/export = 0/0
        # pero no debe lanzar.
        agg.update(0, r)
        assert agg.energy_served_kwh == pytest.approx(50.0)


# =============================================================================
# #3 — Protección anti zip-bomb
# =============================================================================
class TestZipBombGuard:

    def _valid_network_json(self) -> bytes:
        return json.dumps({
            "name": "x", "buses": [], "branches": [], "assets": [],
        }).encode("utf-8")

    def test_empty_bytes_rejected(self):
        from redes_engine.persistence import load_container_from_bytes
        from redes_engine.persistence.project import RSProjectError
        with pytest.raises(RSProjectError, match="vac"):
            load_container_from_bytes(b"")

    def test_json_without_network_rejected(self):
        from redes_engine.persistence import load_container_from_bytes
        from redes_engine.persistence.project import RSProjectError
        with pytest.raises(RSProjectError, match="network"):
            load_container_from_bytes(b'{"foo": 1}')

    def test_too_many_entries_rejected(self):
        from redes_engine.persistence import load_container_from_bytes
        from redes_engine.persistence.container import MAX_ENTRIES
        from redes_engine.persistence.project import RSProjectError

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("network.json", self._valid_network_json())
            for i in range(MAX_ENTRIES + 5):
                zf.writestr(f"junk_{i}.txt", b"x")
        with pytest.raises(RSProjectError, match="entradas"):
            load_container_from_bytes(buf.getvalue())

    def test_high_compression_ratio_rejected(self):
        from redes_engine.persistence import load_container_from_bytes
        from redes_engine.persistence.project import RSProjectError

        # 8 MB de ceros comprimen a unos KB → ratio >> 200×
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("network.json", self._valid_network_json())
            zf.writestr("pad.bin", b"\x00" * (8 * 1024 * 1024))
        with pytest.raises(RSProjectError, match="ratio|descomprimido"):
            load_container_from_bytes(buf.getvalue())

    def test_valid_small_container_still_loads(self):
        # Un .rsproj legítimo y pequeño debe seguir cargando sin problema.
        from redes_engine.persistence import (
            RSProjectContainer, load_container_from_bytes,
        )
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        c = RSProjectContainer.from_network(build_urbanizacion_pastaza())
        data = c.write_zip_bytes()
        loaded = load_container_from_bytes(data)
        assert len(loaded.network.buses) > 0


# =============================================================================
# #2 — Restauración de estado de workflow al recargar
# =============================================================================
class TestWorkflowStateRestore:

    @pytest.fixture(autouse=True)
    def clean_store(self):
        from redes_engine.api.storage import get_store
        get_store().clear()
        yield
        get_store().clear()

    @pytest.fixture
    def client(self):
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient
        from redes_engine.api.main import app
        return TestClient(app)

    def test_active_domains_and_emitted_docs_survive_roundtrip(self, client):
        from redes_engine.api.storage import get_store

        nid = client.post("/api/v1/demo/load").json()["id"]

        # Activar un dominio explícitamente
        client.post(
            f"/api/v1/networks/{nid}/domains",
            json={"domain_ids": ["aereo_mt"], "active": True},
        )
        # Marcar un doc emitido manualmente (simula emisión previa)
        get_store().get(nid).emitted_docs.append("pdf")

        # Guardar → el contenedor persiste el estado de workflow
        res = client.post(f"/api/v1/projects/save/{nid}", json={})
        assert res.status_code == 200
        rsproj_bytes = res.content

        # Recargar como red nueva
        files = {"file": ("p.rsproj", rsproj_bytes, "application/zip")}
        res2 = client.post("/api/v1/projects/load", files=files)
        assert res2.status_code == 201
        nid2 = res2.json()["id"]

        stored2 = get_store().get(nid2)
        # ANTES del fix: ambos quedaban en [] al recargar
        assert "aereo_mt" in stored2.active_domains
        assert "pdf" in stored2.emitted_docs
        # El snapshot de cálculos quedó disponible para inspección
        assert isinstance(stored2.loaded_calculos, dict)
        assert "workflow" in stored2.loaded_calculos


# =============================================================================
# #7 — total_load_kw no debe contar almacenamiento bidireccional (V2G/BESS)
# =============================================================================
class TestTotalLoadExcludesStorage:

    def test_v2g_not_counted_as_load(self):
        from redes_engine.core.graph import (
            Asset, AssetType, Bus, BusType, VoltageLevel,
        )
        from redes_engine.core.network import Network

        net = Network(name="n")
        net.add_bus(Bus(
            id="B1", geometry=(0, 0), voltage_kv=0.22,
            level=VoltageLevel.BT_220_127, bus_type=BusType.MEDIDOR,
        ))
        net.add_asset(Asset(
            id="L1", bus_id="B1", asset_type=AssetType.LOAD_RESIDENCIAL,
            rated_kw=5.0,
        ))
        # V2G es is_ev() Y is_storage(): NO debe contar como demanda
        net.add_asset(Asset(
            id="V1", bus_id="B1", asset_type=AssetType.V2G_BIDIRECTIONAL,
            rated_kw=7.0, capacity_kwh=40.0, bidirectional=True,
        ))
        # BESS puro: tampoco
        net.add_asset(Asset(
            id="BS1", bus_id="B1", asset_type=AssetType.BESS_BTM,
            rated_kw=5.0, capacity_kwh=13.5,
        ))
        # Solo la carga residencial cuenta
        assert net.total_load_kw() == pytest.approx(5.0)


# =============================================================================
# #9 — apply_to_network idempotente (no compone el crecimiento)
# =============================================================================
class TestScenarioIdempotency:

    def test_double_apply_does_not_compound_growth(self):
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        from redes_engine.timeseries import Scenario

        sc = Scenario(
            name="X", year=2030, base_year=2026,
            base_load_growth_pct_per_year=3.0,
            ev_penetration_pct=0.0, pv_penetration_pct=0.0,
        )
        net = build_urbanizacion_pastaza()
        sc.apply_to_network(net, profiles={}, random_seed=1)
        load_after_first = net.total_load_kw()
        # Reaplicar el MISMO escenario no debe volver a escalar (growth²)
        sc.apply_to_network(net, profiles={}, random_seed=1)
        load_after_second = net.total_load_kw()
        assert load_after_second == pytest.approx(load_after_first, rel=1e-9)


# =============================================================================
# #8 — Hosting marca PRE_EXISTING cuando la red ya viola a 0 kW
# =============================================================================
class TestHostingPreExisting:

    def test_pre_existing_violation_flagged(self):
        pytest.importorskip("opendssdirect", reason="OpenDSS no instalado")
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        from redes_engine.hosting import HostingCapacityAnalyzer
        from redes_engine.hosting.results import LimitingFactor
        from redes_engine.timeseries import ProfileLibrary

        # Sobrecargar masivamente la red para forzar subtensión de base
        net = build_urbanizacion_pastaza()
        for a in net.assets.values():
            if a.is_load() and not a.is_storage():
                a.rated_kw *= 50.0

        profiles = ProfileLibrary.ecuador_default(seed=42)
        analyzer = HostingCapacityAnalyzer(net, profiles=profiles)
        results = analyzer.analyze_all(
            n_critical_hours=8, tolerance_kw=50.0, max_kw=500.0,
        )

        # Si algún bus quedó pre-violado, debe marcarse PRE_EXISTING con 0 kW
        pre = [
            b for b in results.bus_results.values()
            if b.load_limiting_factor == LimitingFactor.PRE_EXISTING
            or b.pv_limiting_factor == LimitingFactor.PRE_EXISTING
        ]
        # Al menos un bus pre-violado y su hosting correspondiente debe ser 0
        assert pre, "Se esperaba al menos un bus con violación preexistente"
        for b in pre:
            if b.load_limiting_factor == LimitingFactor.PRE_EXISTING:
                assert b.load_hosting_kw == 0.0
            if b.pv_limiting_factor == LimitingFactor.PRE_EXISTING:
                assert b.pv_hosting_kw == 0.0


# =============================================================================
# Trafo más cargado: por tipo real (is_transformer), no por substring "T"
# =============================================================================
class TestTransformerDetection:

    def test_peak_transformer_by_type_not_substring(self):
        from redes_engine.core.results import (
            BranchFlowResult, ComplianceStatus, PowerFlowResult,
        )
        from redes_engine.timeseries.aggregator import AnnualAggregator

        def _result(line_load, trafo_load):
            r = PowerFlowResult(converged=True, total_power_kw=10.0,
                                net_power_kw=10.0, total_losses_kw=0.1)
            # "LINE_T" contiene 'T' pero NO es trafo (el bug viejo lo elegía)
            r.branch_flows["LINE_T"] = BranchFlowResult(
                branch_id="LINE_T", p_kw=1, q_kvar=0, s_kva=1, current_a=1,
                rated_a=100, loading_pct=line_load, losses_kw=0, losses_kvar=0,
                compliance=ComplianceStatus.OK, is_transformer=False,
            )
            # "X1" es el trafo real (sin 'T' en el nombre)
            r.branch_flows["X1"] = BranchFlowResult(
                branch_id="X1", p_kw=1, q_kvar=0, s_kva=1, current_a=1,
                rated_a=100, loading_pct=trafo_load, losses_kw=0, losses_kvar=0,
                compliance=ComplianceStatus.OK, is_transformer=True,
            )
            return r

        agg = AnnualAggregator()
        agg.update(0, _result(10.0, 10.0))   # crea stats
        agg.update(1, _result(99.0, 80.0))   # incrementa loading → dispara

        # El pico de trafo debe ser X1 (80%), NO la línea "LINE_T" (99%)
        assert agg.peak_transformer_id == "X1"
        assert agg.peak_transformer_loading_pct == pytest.approx(80.0)


# =============================================================================
# Network.remove_asset mantiene el índice por bus consistente
# =============================================================================
class TestRemoveAsset:

    def test_remove_asset_updates_index(self):
        from redes_engine.core.graph import (
            Asset, AssetType, Bus, BusType, VoltageLevel,
        )
        from redes_engine.core.network import Network

        net = Network(name="n")
        net.add_bus(Bus(
            id="B1", geometry=(0, 0), voltage_kv=0.22,
            level=VoltageLevel.BT_220_127, bus_type=BusType.MEDIDOR,
        ))
        net.add_asset(Asset(id="L1", bus_id="B1",
                            asset_type=AssetType.LOAD_RESIDENCIAL, rated_kw=2))
        net.add_asset(Asset(id="L2", bus_id="B1",
                            asset_type=AssetType.LOAD_RESIDENCIAL, rated_kw=3))
        assert net.remove_asset("L1") is True
        assert "L1" not in net.assets
        # El índice por bus ya no debe listar L1, pero sí L2
        ids = [a.id for a in net.assets_at_bus("B1")]
        assert ids == ["L2"]
        # Eliminar algo inexistente devuelve False (sin excepción)
        assert net.remove_asset("NOPE") is False


# =============================================================================
# Inversión: sin ingresos antes de ejecutar el CAPEX (capex_year>0)
# =============================================================================
class TestInvestmentCapexYear:

    def test_no_revenue_before_capex_year(self):
        from redes_engine.engineering import (
            InvestmentAnalyzer, InvestmentAssumptions,
        )
        ana = InvestmentAnalyzer(InvestmentAssumptions(
            horizon_years=5, inflation_rate=0.0,
            indirect_costs_pct=0.0, contingency_pct=0.0,
            om_pct_of_capex_per_year=0.05,
        ))
        r = ana.analyze(
            capex_direct_usd=100_000,
            annual_capacity_savings_usd=20_000,
            capex_year=2,
        )
        # Años 0 y 1 (antes de invertir): sin OPEX ni ingresos
        for t in (0, 1):
            cf = r.cashflows[t]
            assert cf.revenue_savings_usd == 0.0
            assert cf.opex_om_usd == 0.0
        # El CAPEX cae en el año 2
        assert r.cashflows[2].capex_usd == pytest.approx(-100_000)
        # Y a partir del año 3 sí hay ingresos
        assert r.cashflows[3].revenue_savings_usd > 0


# =============================================================================
# Serialización: coerción de tipos de los campos socioeconómicos
# =============================================================================
class TestSerializationCoercion:

    def test_roof_fields_coerced_from_strings(self):
        from redes_engine.persistence.serialization import dict_to_asset

        a = dict_to_asset({
            "id": "L1", "bus_id": "B1", "asset_type": "LOAD_RESIDENCIAL",
            "rated_kw": 2.0,
            "socioeconomic_stratum": "4",      # string → int
            "has_roof_pv_potential": 1,         # truthy → bool
            "roof_area_m2": "85.5",            # string → float
        })
        assert a.socioeconomic_stratum == 4
        assert a.has_roof_pv_potential is True
        assert isinstance(a.roof_area_m2, float)
        assert a.roof_area_m2 == pytest.approx(85.5)

    def test_none_roof_fields_stay_none(self):
        from redes_engine.persistence.serialization import dict_to_asset

        a = dict_to_asset({
            "id": "L1", "bus_id": "B1", "asset_type": "LOAD_RESIDENCIAL",
            "rated_kw": 2.0,
        })
        assert a.socioeconomic_stratum is None
        assert a.has_roof_pv_potential is None
        assert a.roof_area_m2 is None


# =============================================================================
# Buses DC excluidos de los límites AC de caída de tensión (ARCERNNR)
# =============================================================================
class TestDCBusCompliance:

    def test_bus_is_dc_helpers(self):
        from redes_engine.core.graph import (
            Bus, BusType, VoltageLevel,
        )
        dc = Bus(id="DC1", geometry=(0, 0), voltage_kv=0.480,
                 level=VoltageLevel.DC_BUS_480, bus_type=BusType.MEDIDOR)
        assert dc.is_dc() is True
        # Un bus DC no se clasifica como BT ni MT (AC)
        assert dc.is_bt() is False
        assert dc.is_mt() is False

    def test_dc_bus_voltage_result_not_violation(self):
        from redes_engine.core.results import BusVoltageResult, ComplianceStatus
        # Caída enorme (15%) que en BT sería VIOLATION
        r = BusVoltageResult(
            bus_id="DC1", v_magnitude_kv=0.40, v_pu=0.85,
            v_drop_pct=15.0, angle_deg=0.0, voltage_nominal_kv=0.480,
            is_dc=True,
        )
        r.evaluate_compliance()
        # DC → no evaluado bajo límites AC
        assert r.compliance == ComplianceStatus.UNKNOWN

    def test_compliance_analyzer_skips_dc_bus(self):
        from redes_engine.core.compliance import ARCERNNR_EC, ComplianceAnalyzer
        from redes_engine.core.results import (
            BusVoltageResult, ComplianceStatus, PowerFlowResult,
        )
        result = PowerFlowResult(converged=True)
        # Bus BT normal con caída severa → VIOLATION
        result.bus_voltages["B1"] = BusVoltageResult(
            bus_id="B1", v_magnitude_kv=0.20, v_pu=0.85, v_drop_pct=15.0,
            angle_deg=0.0, voltage_nominal_kv=0.22, is_dc=False,
        )
        # Bus DC con la misma caída → NO debe contar como violación
        result.bus_voltages["DC1"] = BusVoltageResult(
            bus_id="DC1", v_magnitude_kv=0.40, v_pu=0.85, v_drop_pct=15.0,
            angle_deg=0.0, voltage_nominal_kv=0.480, is_dc=True,
        )
        report = ComplianceAnalyzer(ARCERNNR_EC).analyze(result)
        violated_ids = {f.element_id for f in report.violations()
                        if f.category == "voltaje"}
        assert "B1" in violated_ids
        assert "DC1" not in violated_ids


# =============================================================================
# MILP diario: cierre de ciclo (no agota la batería)
# =============================================================================
class TestMILPCycleClosure:

    def _final_soc(self, state, plan):
        """Reconstruye el SoC final aplicando el plan horario."""
        soc = state.soc
        for p in plan:
            if p > 0:       # carga
                soc += state.eff_charge * p / state.capacity_kwh
            elif p < 0:     # descarga
                soc += p / state.eff_discharge / state.capacity_kwh
        return soc

    def test_cycle_closure_prevents_drain(self):
        pytest.importorskip("pulp", reason="PuLP no instalado")
        from redes_engine.timeseries.dispatch import BESSState, MILPDailyDispatch

        def _state():
            return BESSState(asset_id="B", capacity_kwh=200.0, rated_kw=50.0,
                             soc=0.6, soc_min=0.2, soc_max=0.95)

        # Escenario con un pico marcado a la hora 19 (incentiva descargar)
        load = [50.0] * 24
        load[19] = 300.0
        pv = [0.0] * 24

        # CON cierre de ciclo: el SoC final no debe caer por debajo del inicial
        d_closed = MILPDailyDispatch(objective="loading", cycle_closure=True)
        st = _state()
        plan_closed = d_closed._solve_day(0, {"B": st}, load, pv, 100.0)["B"]
        soc_closed = self._final_soc(st, plan_closed)
        assert soc_closed >= st.soc - 1e-6, (
            f"cycle_closure no respetado: soc_final={soc_closed:.3f} < {st.soc}"
        )

        # SIN cierre: se permite terminar por debajo (agotando reserva)
        d_open = MILPDailyDispatch(objective="loading", cycle_closure=False)
        st2 = _state()
        plan_open = d_open._solve_day(0, {"B": st2}, load, pv, 100.0)["B"]
        soc_open = self._final_soc(st2, plan_open)
        # El caso sin cierre termina con SoC menor o igual que el cerrado
        assert soc_open <= soc_closed + 1e-6

    def test_cycle_closure_always_feasible_with_idle(self):
        # Aun sin margen para mover energía, el cierre es factible (idle).
        pytest.importorskip("pulp", reason="PuLP no instalado")
        from redes_engine.timeseries.dispatch import BESSState, MILPDailyDispatch

        st = BESSState(asset_id="B", capacity_kwh=10.0, rated_kw=5.0,
                       soc=0.5, soc_min=0.45, soc_max=0.55)  # margen mínimo
        d = MILPDailyDispatch(objective="loading", cycle_closure=True)
        plan = d._solve_day(0, {"B": st}, [10.0] * 24, [0.0] * 24, 50.0)["B"]
        # Debe devolver un plan de 24 valores sin lanzar (factible)
        assert len(plan) == 24
        soc_final = self._final_soc(st, plan)
        assert soc_final >= st.soc - 1e-6


# =============================================================================
# Rehidratación COMPLETA de resultados desde .rsproj (objetos vivos)
# =============================================================================
class TestResultsRehydration:

    def test_power_flow_round_trip(self):
        from redes_engine.core.results import (
            BranchFlowResult, BusVoltageResult, ComplianceStatus,
            PowerFlowResult,
        )
        from redes_engine.persistence.results_full import (
            power_flow_from_dict, power_flow_to_dict,
        )
        r = PowerFlowResult(
            converged=True, iterations=7, total_power_kw=120.0,
            net_power_kw=120.0, total_losses_kw=3.5, losses_pct=2.9,
        )
        r.bus_voltages["B1"] = BusVoltageResult(
            bus_id="B1", v_magnitude_kv=22.5, v_pu=0.987, v_drop_pct=1.3,
            angle_deg=0.0, voltage_nominal_kv=22.8,
            compliance=ComplianceStatus.OK, is_dc=False,
        )
        r.branch_flows["T1"] = BranchFlowResult(
            branch_id="T1", p_kw=100, q_kvar=10, s_kva=100.5, current_a=50,
            rated_a=100, loading_pct=50.0, losses_kw=1.0, losses_kvar=0.5,
            compliance=ComplianceStatus.OK, is_transformer=True,
        )
        r2 = power_flow_from_dict(power_flow_to_dict(r))
        assert r2.converged and r2.iterations == 7
        assert r2.net_power_kw == 120.0
        assert r2.bus_voltages["B1"].v_pu == pytest.approx(0.987)
        assert r2.bus_voltages["B1"].compliance == ComplianceStatus.OK
        assert r2.branch_flows["T1"].is_transformer is True
        assert r2.branch_flows["T1"].loading_pct == pytest.approx(50.0)

    def test_compliance_round_trip(self):
        from redes_engine.core.compliance import (
            ComplianceFinding, ComplianceReport, NormativeFramework,
        )
        from redes_engine.core.results import ComplianceStatus
        from redes_engine.persistence.results_full import (
            compliance_from_dict, compliance_to_dict,
        )
        c = ComplianceReport(
            framework=NormativeFramework.ARCERNNR_EC_002_20,
            overall_status=ComplianceStatus.VIOLATION,
        )
        c.findings.append(ComplianceFinding(
            severity=ComplianceStatus.VIOLATION, category="voltaje",
            element_id="B9", actual_value=9.1, limit_value=8.0, units="%",
            message="ΔV excede",
        ))
        c2 = compliance_from_dict(compliance_to_dict(c))
        assert c2.framework == NormativeFramework.ARCERNNR_EC_002_20
        assert c2.overall_status == ComplianceStatus.VIOLATION
        assert len(c2.violations()) == 1
        assert c2.violations()[0].element_id == "B9"

    def test_hosting_and_annual_round_trip(self):
        from redes_engine.hosting.results import (
            BusHostingCapacity, HostingCapacityResults, LimitingFactor,
        )
        from redes_engine.persistence.results_full import (
            annual_from_dict, annual_to_dict, hosting_from_dict, hosting_to_dict,
        )
        from redes_engine.timeseries.aggregator import (
            AnnualResults, BusAnnualStats,
        )
        h = HostingCapacityResults(network_name="N", n_buses_analyzed=1)
        h.bus_results["B1"] = BusHostingCapacity(
            bus_id="B1", voltage_nominal_kv=22.8, pv_hosting_kw=120.0,
            pv_limiting_factor=LimitingFactor.OVERVOLTAGE,
            load_hosting_kw=0.0, load_limiting_factor=LimitingFactor.PRE_EXISTING,
        )
        h2 = hosting_from_dict(hosting_to_dict(h))
        assert h2.bus_results["B1"].pv_hosting_kw == pytest.approx(120.0)
        assert h2.bus_results["B1"].pv_limiting_factor == LimitingFactor.OVERVOLTAGE
        assert h2.bus_results["B1"].load_limiting_factor == LimitingFactor.PRE_EXISTING

        a = AnnualResults(scenario_name="S", n_hours_simulated=8760,
                          peak_demand_kw=200.0, total_losses_mwh=12.3)
        a.bus_stats["B1"] = BusAnnualStats(
            bus_id="B1", voltage_nominal_kv=22.8, v_pu_min=0.94,
            hours_in_violation=5,
        )
        a2 = annual_from_dict(annual_to_dict(a))
        assert a2.n_hours_simulated == 8760
        assert a2.peak_demand_kw == pytest.approx(200.0)
        assert a2.bus_stats["B1"].hours_in_violation == 5

    def test_api_solve_save_load_restores_live_results(self):
        pytest.importorskip("opendssdirect", reason="OpenDSS no instalado")
        pytest.importorskip("fastapi")
        from fastapi.testclient import TestClient

        from redes_engine.api.main import app
        from redes_engine.api.storage import get_store

        get_store().clear()
        try:
            client = TestClient(app)
            nid = client.post("/api/v1/demo/load").json()["id"]
            # Resolver flujo → genera last_solve_result + last_compliance_report
            res_solve = client.post(f"/api/v1/networks/{nid}/solve", json={})
            assert res_solve.status_code == 200

            # Guardar y recargar
            saved = client.post(f"/api/v1/projects/save/{nid}", json={}).content
            files = {"file": ("p.rsproj", saved, "application/zip")}
            nid2 = client.post("/api/v1/projects/load", files=files).json()["id"]

            stored2 = get_store().get(nid2)
            # ANTES del fix: estos quedaban en None al recargar
            assert stored2.last_solve_result is not None
            assert stored2.last_solve_result.converged is True
            assert len(stored2.last_solve_result.bus_voltages) > 0
            assert stored2.last_compliance_report is not None
            # El workflow ya refleja la fase de cálculo cumplida tras recargar
            wf = client.get(f"/api/v1/networks/{nid2}/workflow").json()
            calc = next(p for p in wf["phases"] if p["id"] == "calculo")
            assert calc["progress_pct"] > 0
        finally:
            get_store().clear()
