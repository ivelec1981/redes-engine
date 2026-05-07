# -*- coding: utf-8 -*-
"""
Ejemplo end-to-end: construir → resolver → analizar → reportar.

Demuestra el bridge real con OpenDSS:
    1. Construye la urbanización Pastaza
    2. Resuelve el flujo de potencia con opendssdirect
    3. Trae los resultados a objetos tipados
    4. Evalúa cumplimiento normativo (ARCERNNR Reg. 002/20)
    5. Imprime reportes ejecutivo + detallado
"""

import sys

from ..core.compliance import ARCERNNR_EC, ComplianceAnalyzer
from ..io.opendss_solver import OpenDSSNotAvailableError, OpenDSSSolver
from .urbanizacion_mixta import build_urbanizacion_pastaza


def run() -> int:
    # ── 1. Construir la red ───────────────────────────────────────────
    print("📐 Construyendo red 'El Pastaza'...")
    net = build_urbanizacion_pastaza()
    print(net.summary())

    # ── 2. Resolver con OpenDSS ───────────────────────────────────────
    print("\n⚡ Resolviendo flujo de potencia con OpenDSS...\n")
    try:
        with OpenDSSSolver(net, keep_files=True) as solver:
            converged = solver.solve(max_iterations=100, tolerance=1e-4)

            if not converged:
                print("❌ El solver NO convergió.")
                return 2

            # ── 3. Recolectar resultados ──────────────────────────────
            result = solver.collect_results(
                mt_voltage_limit_pct=5.0,
                bt_voltage_limit_pct=8.0,
            )

            # ── 4. Reporte ejecutivo ──────────────────────────────────
            print(result.summary())

            # ── 5. Tabla de voltajes ──────────────────────────────────
            print("\n📊 VOLTAJES POR BUS (ordenados por mayor caída):")
            print(result.voltage_table(sort_by="drop"))

            # ── 6. Tabla de flujos ────────────────────────────────────
            print("\n📊 FLUJOS POR BRANCH:")
            print(result.branch_table())

            # ── 7. Análisis de cumplimiento ───────────────────────────
            print("\n🛡 EVALUANDO CUMPLIMIENTO NORMATIVO (ARCERNNR 002/20)...\n")
            analyzer = ComplianceAnalyzer(ARCERNNR_EC)
            report = analyzer.analyze(result)
            print(report.summary())

            # ── 8. Decisión ───────────────────────────────────────────
            from ..core.results import ComplianceStatus
            if report.overall_status == ComplianceStatus.VIOLATION:
                print("\n📌 DECISIÓN: La red NO cumple normativa.")
                print("   Acciones recomendadas:")
                for v in report.violations():
                    if v.category == "voltaje":
                        print(f"   • Reforzar conductor o agregar regulador "
                              f"para mejorar tensión en {v.element_id}")
                    elif v.category == "ampacidad":
                        print(f"   • Reemplazar conductor de {v.element_id} "
                              f"por uno de mayor capacidad")
                    elif v.category == "perdidas":
                        print(f"   • Optimizar topología o reubicar trafo "
                              f"para reducir pérdidas")
                return 1

            print("\n📌 DECISIÓN: La red cumple normativa. ✅")
            return 0

    except OpenDSSNotAvailableError as e:
        print(f"❌ {e}")
        return 3


if __name__ == "__main__":
    sys.exit(run())
