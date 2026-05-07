# -*- coding: utf-8 -*-
"""
redes_engine.io.opendss_bridge
===============================

Exporta un objeto Network al formato de archivo .dss compatible
con OpenDSS (EPRI). Genera un script ejecutable directamente por
opendssdirect (Python) o por OpenDSS standalone.

Mapeo de entidades:
    Bus              → New Bus / barra OpenDSS implícita
    Branch (line)    → New Line.<id>
    Branch (trafo)   → New Transformer.<id>
    Asset (load/EV)  → New Load.<id>
    Asset (PV)       → New Generator.<id>  (modelo de generación constante)
    Asset (BESS)     → New Storage.<id>
"""

from typing import List

from ..core.graph import AssetType, BranchType
from ..core.network import Network


class OpenDSSExporter:
    """
    Convierte un Network al formato .dss de OpenDSS.

    Uso típico:
        net = build_my_network()
        exporter = OpenDSSExporter(net)
        exporter.export("circuito.dss")
        # Luego en Python:
        #   import opendssdirect as dss
        #   dss.Text.Command("Redirect circuito.dss")
        #   dss.Solution.Solve()
    """

    def __init__(self, network: Network):
        self.net = network

    # =========================================================================
    # ENTRADA PRINCIPAL
    # =========================================================================
    def export(
        self,
        output_path: str,
        base_frequency_hz: float = 60.0,
        slack_pu: float = 1.02,
    ) -> str:
        """
        Genera el archivo .dss completo.

        Parameters
        ----------
        output_path : str
            Ruta del archivo .dss a crear.
        base_frequency_hz : float
            Frecuencia base del sistema (60 Hz Ecuador).
        slack_pu : float
            Voltaje del bus slack en pu (1.02 = 2% sobre nominal).
        """
        lines: List[str] = []

        # ── Cabecera ────────────────────────────────────────────────
        lines.append("// ═══════════════════════════════════════════════════════════")
        lines.append(f"// Generado por redes_engine — Red: {self.net.name}")
        lines.append("// ═══════════════════════════════════════════════════════════")
        lines.append("Clear")
        lines.append(f"Set DefaultBaseFrequency={base_frequency_hz}")
        lines.append("")

        # ── Circuito (fuente / slack) ───────────────────────────────
        lines.extend(self._emit_circuit(slack_pu))
        lines.append("")

        # ── Líneas ──────────────────────────────────────────────────
        lines.extend(self._emit_lines())
        lines.append("")

        # ── Transformadores ─────────────────────────────────────────
        lines.extend(self._emit_transformers())
        lines.append("")

        # ── Cargas ──────────────────────────────────────────────────
        lines.extend(self._emit_loads())
        lines.append("")

        # ── Generadores PV ──────────────────────────────────────────
        lines.extend(self._emit_generators())
        lines.append("")

        # ── Almacenamiento (BESS / V2G) ─────────────────────────────
        lines.extend(self._emit_storage())
        lines.append("")

        # ── Cierre y solución ───────────────────────────────────────
        lines.extend(self._emit_voltage_bases())
        lines.append("CalcVoltageBases")
        lines.append("Solve")
        lines.append("")
        lines.append("// Reportes útiles:")
        lines.append("// Show Voltages LN Nodes")
        lines.append("// Show Powers kVA Elements")
        lines.append("// Show Losses")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return output_path

    # =========================================================================
    # SECCIONES DEL .DSS
    # =========================================================================

    def _emit_circuit(self, slack_pu: float) -> List[str]:
        root = self.net.find_root_bus()
        if root is None:
            return ["// (sin buses — circuito vacío)"]
        return [
            "// Fuente (slack bus)",
            f"New Circuit.{self.net.name} "
            f"basekv={root.voltage_kv} "
            f"bus1={root.id} "
            f"pu={slack_pu} "
            f"phases=3 "
            f"MVAsc3=20000 MVAsc1=21000",
        ]

    def _emit_lines(self) -> List[str]:
        out = ["// ─── Líneas (aéreas y subterráneas) ───"]
        for br in self.net.branches.values():
            if not br.is_line():
                continue
            length_km = max(br.length_m / 1000.0, 1e-6)
            r1_per_km = br.r_ohm / length_km if length_km > 0 else 0.0
            x1_per_km = br.x_ohm / length_km if length_km > 0 else 0.0
            out.append(
                f"New Line.{br.id} "
                f"bus1={br.bus_from} bus2={br.bus_to} "
                f"phases=3 "
                f"r1={r1_per_km:.4f} x1={x1_per_km:.4f} "
                f"length={length_km:.4f} units=km "
                f"normamps={br.rated_a:.1f}"
            )
        return out

    def _emit_transformers(self) -> List[str]:
        out = ["// ─── Transformadores ───"]
        for br in self.net.transformers():
            kva = br.kva or 75.0
            kvp = br.kv_primary or self.net.buses[br.bus_from].voltage_kv
            kvs = br.kv_secondary or self.net.buses[br.bus_to].voltage_kv
            xhl = (br.impedance_pu or 0.04) * 100.0  # OpenDSS usa porcentaje
            out.append(
                f"New Transformer.{br.id} "
                f"phases=3 windings=2 "
                f"buses=({br.bus_from} {br.bus_to}) "
                f"conns=(delta wye) "
                f"kvs=({kvp} {kvs}) "
                f"kvas=({kva} {kva}) "
                f"%loadloss=1.5 xhl={xhl:.2f}"
            )
        return out

    def _emit_loads(self) -> List[str]:
        out = ["// ─── Cargas (incluye VE como cargas controlables) ───"]
        load_types = (
            AssetType.LOAD_RESIDENCIAL, AssetType.LOAD_COMERCIAL,
            AssetType.LOAD_INDUSTRIAL, AssetType.ALUMBRADO_PUBLICO,
            AssetType.EV_CHARGER_AC_L1, AssetType.EV_CHARGER_AC_L2,
            AssetType.EV_CHARGER_DC_FAST, AssetType.EV_CHARGER_DC_ULTRA,
            AssetType.EV_FLEET_DEPOT,
        )
        for asset in self.net.assets.values():
            if asset.asset_type not in load_types:
                continue
            bus = self.net.buses[asset.bus_id]
            out.append(
                f"New Load.{asset.id} "
                f"bus1={asset.bus_id} phases=3 "
                f"kv={bus.voltage_kv:.4f} "
                f"kw={asset.rated_kw:.2f} "
                f"kvar={asset.rated_kvar:.2f} "
                f"model=1 "
                f"// {asset.asset_type.value}"
            )
        return out

    def _emit_generators(self) -> List[str]:
        out = ["// ─── Generadores PV / Eólico / Cogen ───"]
        gen_types = (
            AssetType.SOLAR_PV_RESID, AssetType.SOLAR_PV_COMERCIAL,
            AssetType.SOLAR_PV_UTILITY, AssetType.EOLICO,
            AssetType.COGENERACION,
        )
        for asset in self.net.assets.values():
            if asset.asset_type not in gen_types:
                continue
            bus = self.net.buses[asset.bus_id]
            out.append(
                f"New Generator.{asset.id} "
                f"bus1={asset.bus_id} phases=3 "
                f"kv={bus.voltage_kv:.4f} "
                f"kw={asset.rated_kw:.2f} "
                f"pf=1.0 model=1 "
                f"// {asset.asset_type.value}"
            )
        return out

    def _emit_storage(self) -> List[str]:
        out = ["// ─── Almacenamiento (BESS / V2G) ───"]
        storage_types = (
            AssetType.BESS_BTM, AssetType.BESS_C_AND_I,
            AssetType.BESS_GRID_SCALE, AssetType.PV_BESS_HYBRID,
            AssetType.V2G_BIDIRECTIONAL,
        )
        for asset in self.net.assets.values():
            if asset.asset_type not in storage_types:
                continue
            bus = self.net.buses[asset.bus_id]
            soc_pct = (asset.soc_initial or 0.5) * 100.0
            eff_c = (asset.efficiency_charge or 0.95) * 100.0
            eff_d = (asset.efficiency_discharge or 0.95) * 100.0
            out.append(
                f"New Storage.{asset.id} "
                f"bus1={asset.bus_id} phases=3 "
                f"kv={bus.voltage_kv:.4f} "
                f"kwrated={asset.rated_kw:.2f} "
                f"kwhrated={asset.capacity_kwh or 0.0:.2f} "
                f"%stored={soc_pct:.1f} "
                f"%effcharge={eff_c:.1f} "
                f"%effdischarge={eff_d:.1f} "
                f"// {asset.asset_type.value}"
            )
        return out

    def _emit_voltage_bases(self) -> List[str]:
        """Lista única de voltajes presentes en la red."""
        voltages = sorted({b.voltage_kv for b in self.net.buses.values()}, reverse=True)
        bases = " ".join(f"{v}" for v in voltages)
        return [f"Set VoltageBases=[{bases}]"]
