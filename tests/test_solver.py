# -*- coding: utf-8 -*-
"""
Tests del bridge OpenDSS — solver + compliance.

Si opendssdirect no está disponible, los tests se marcan como skipped.
"""

import os
import sys

# Permitir ejecutar tests sin instalar el paquete
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest

from redes_engine.core.compliance import (
    ARCERNNR_EC, ComplianceAnalyzer, ComplianceStatus, NormativeFramework,
)
from redes_engine.core.results import (
    BranchFlowResult, BusVoltageResult, PowerFlowResult,
)


# =============================================================================
# Detectar opendssdirect (skip si no está)
# =============================================================================
opendss = pytest.importorskip(
    "opendssdirect",
    reason="opendssdirect no instalado — tests del solver omitidos",
)


# =============================================================================
# Tests del solver
# =============================================================================
class TestOpenDSSSolver:

    @pytest.fixture
    def net(self):
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        return build_urbanizacion_pastaza()

    def test_solver_converges(self, net):
        from redes_engine.io.opendss_solver import OpenDSSSolver

        with OpenDSSSolver(net) as solver:
            converged = solver.solve()
            assert converged is True

    def test_solver_returns_voltages(self, net):
        from redes_engine.io.opendss_solver import OpenDSSSolver

        with OpenDSSSolver(net) as solver:
            assert solver.solve()
            result = solver.collect_results()
            assert result.converged
            # Debe haber voltajes para todos los buses (o casi)
            assert len(result.bus_voltages) >= 5

    def test_solver_returns_branch_flows(self, net):
        from redes_engine.io.opendss_solver import OpenDSSSolver

        with OpenDSSSolver(net) as solver:
            assert solver.solve()
            result = solver.collect_results()
            # Debe haber flujos para líneas y trafos
            assert len(result.branch_flows) >= 5

    def test_root_bus_close_to_nominal(self, net):
        """El bus raíz (slack) debe estar cerca de 1.0 pu (típicamente 1.02)."""
        from redes_engine.io.opendss_solver import OpenDSSSolver

        with OpenDSSSolver(net) as solver:
            assert solver.solve()
            result = solver.collect_results()
            root_id = net.find_root_bus().id
            assert root_id in result.bus_voltages
            v_root = result.bus_voltages[root_id]
            # El slack está fijado a 1.02 pu por defecto
            assert 0.98 <= v_root.v_pu <= 1.05

    def test_total_losses_positive(self, net):
        """Las pérdidas totales deben ser positivas (no cero, no negativas)."""
        from redes_engine.io.opendss_solver import OpenDSSSolver

        with OpenDSSSolver(net) as solver:
            assert solver.solve()
            result = solver.collect_results()
            assert result.total_losses_kw > 0
            assert result.losses_pct > 0


# =============================================================================
# Tests del analizador de cumplimiento (no requieren OpenDSS)
# =============================================================================
class TestCompliance:

    def test_voltage_within_limit_passes(self):
        analyzer = ComplianceAnalyzer(ARCERNNR_EC)
        result = PowerFlowResult(converged=True)
        result.bus_voltages["B1"] = BusVoltageResult(
            bus_id="B1", v_magnitude_kv=22.5, v_pu=0.987,
            v_drop_pct=1.3, angle_deg=0.0, voltage_nominal_kv=22.8,
        )
        result.branch_flows["L1"] = BranchFlowResult(
            branch_id="L1", p_kw=10, q_kvar=2, s_kva=10.2,
            current_a=50, rated_a=200, loading_pct=25,
            losses_kw=0.1, losses_kvar=0.05,
        )
        report = analyzer.analyze(result)
        assert report.overall_status == ComplianceStatus.OK

    def test_voltage_violation_detected(self):
        analyzer = ComplianceAnalyzer(ARCERNNR_EC)
        result = PowerFlowResult(converged=True)
        # Bus BT con caída de 12% (excede 8%)
        result.bus_voltages["BT_far"] = BusVoltageResult(
            bus_id="BT_far", v_magnitude_kv=0.194, v_pu=0.88,
            v_drop_pct=12.0, angle_deg=0.0, voltage_nominal_kv=0.220,
        )
        report = analyzer.analyze(result)
        assert report.overall_status == ComplianceStatus.VIOLATION
        assert len(report.violations()) >= 1

    def test_overload_detected(self):
        analyzer = ComplianceAnalyzer(ARCERNNR_EC)
        result = PowerFlowResult(converged=True)
        result.bus_voltages["B1"] = BusVoltageResult(
            bus_id="B1", v_magnitude_kv=22.5, v_pu=0.987,
            v_drop_pct=1.3, angle_deg=0.0, voltage_nominal_kv=22.8,
        )
        # Línea sobrecargada al 110%
        result.branch_flows["L_overloaded"] = BranchFlowResult(
            branch_id="L_overloaded", p_kw=100, q_kvar=20, s_kva=102,
            current_a=220, rated_a=200, loading_pct=110,
            losses_kw=2.5, losses_kvar=1.5,
        )
        report = analyzer.analyze(result)
        assert report.overall_status == ComplianceStatus.VIOLATION
        violations = [v for v in report.violations() if v.category == "ampacidad"]
        assert len(violations) >= 1

    def test_warning_threshold(self):
        analyzer = ComplianceAnalyzer(ARCERNNR_EC)
        result = PowerFlowResult(converged=True)
        # Línea al 90% (warning, no violación)
        result.bus_voltages["B1"] = BusVoltageResult(
            bus_id="B1", v_magnitude_kv=22.0, v_pu=0.965,
            v_drop_pct=3.5, angle_deg=0.0, voltage_nominal_kv=22.8,
        )
        result.branch_flows["L_warn"] = BranchFlowResult(
            branch_id="L_warn", p_kw=80, q_kvar=10, s_kva=81,
            current_a=180, rated_a=200, loading_pct=90,
            losses_kw=1.8, losses_kvar=0.8,
        )
        report = analyzer.analyze(result)
        assert report.overall_status == ComplianceStatus.WARNING
        assert len(report.warnings()) >= 1


# =============================================================================
# Test integral end-to-end
# =============================================================================
class TestEndToEnd:

    def test_full_pipeline(self):
        """Build → Solve → Collect → Analyze."""
        from redes_engine.examples.urbanizacion_mixta import (
            build_urbanizacion_pastaza,
        )
        from redes_engine.io.opendss_solver import OpenDSSSolver

        net = build_urbanizacion_pastaza()
        with OpenDSSSolver(net) as solver:
            assert solver.solve()
            result = solver.collect_results()
            assert result.converged

            analyzer = ComplianceAnalyzer(ARCERNNR_EC)
            report = analyzer.analyze(result)

            # El reporte debe tener al menos un finding por bus
            assert len(report.findings) >= len(result.bus_voltages)

            # El status global debe ser uno de los enum
            assert report.overall_status in (
                ComplianceStatus.OK,
                ComplianceStatus.WARNING,
                ComplianceStatus.VIOLATION,
            )
