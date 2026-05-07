# -*- coding: utf-8 -*-
"""
redes_engine.reports.charts
============================

Genera figuras matplotlib en buffer PNG para embeber en PDF/Word.

Catálogo:
    - bar_voltage_profile     barras de caída de voltaje por bus
    - bar_branch_loading      barras de % de carga por elemento
    - hosting_capacity_chart  ranking de capacidad PV/Load por bus
    - annual_demand_curve     curva de demanda 8760h
"""

import io
from typing import Any, Optional

# Backend no-interactivo (sin GUI) para servidor
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


# =============================================================================
# Estilo común (paleta y tipografía)
# =============================================================================
def _apply_style(ax, title: str = ""):
    ax.set_facecolor("#FAFBFC")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors="#5a6373", labelsize=8)
    ax.title.set_fontsize(11)
    ax.title.set_fontweight("bold")
    ax.title.set_color("#1a237e")
    ax.xaxis.label.set_fontsize(9)
    ax.yaxis.label.set_fontsize(9)
    ax.grid(True, axis="y", alpha=0.3, linestyle="--")
    if title:
        ax.set_title(title)


COLOR_OK         = "#27ae60"
COLOR_WARNING    = "#f39c12"
COLOR_VIOLATION  = "#c0392b"


def _color_for_compliance(status: str) -> str:
    return {
        "ok": COLOR_OK,
        "warning": COLOR_WARNING,
        "violation": COLOR_VIOLATION,
    }.get(status, "#7f8c8d")


# =============================================================================
# Chart 1: Barras de caída de voltaje
# =============================================================================
def bar_voltage_profile(flow_result: Any, max_bars: int = 20) -> bytes:
    """Devuelve PNG en bytes con un gráfico de caída de voltaje por bus."""
    buses = sorted(
        flow_result.bus_voltages.values(),
        key=lambda v: -abs(v.v_drop_pct),
    )[:max_bars]

    ids = [b.bus_id for b in buses]
    drops = [b.v_drop_pct for b in buses]
    colors = [_color_for_compliance(b.compliance.value) for b in buses]

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=120)
    bars = ax.bar(ids, drops, color=colors, edgecolor="#2c3e50", linewidth=0.5)

    # Líneas de referencia normativa
    ax.axhline(5.0, color=COLOR_WARNING, linestyle="--",
               linewidth=0.8, label="Límite MT ±5%")
    ax.axhline(-5.0, color=COLOR_WARNING, linestyle="--", linewidth=0.8)
    ax.axhline(8.0, color=COLOR_VIOLATION, linestyle=":",
               linewidth=0.8, label="Límite BT ±8%")
    ax.axhline(-8.0, color=COLOR_VIOLATION, linestyle=":", linewidth=0.8)

    ax.set_xlabel("Bus")
    ax.set_ylabel("Caída de voltaje (%)")
    _apply_style(ax, "Perfil de caída de voltaje por bus")
    ax.legend(fontsize=7, loc="upper right")
    plt.xticks(rotation=45, ha="right", fontsize=7)
    plt.tight_layout()

    return _save_png(fig)


# =============================================================================
# Chart 2: Barras de carga (%) por branch
# =============================================================================
def bar_branch_loading(flow_result: Any, max_bars: int = 20) -> bytes:
    branches = sorted(
        flow_result.branch_flows.values(),
        key=lambda b: -b.loading_pct,
    )[:max_bars]
    ids = [b.branch_id for b in branches]
    loads = [b.loading_pct for b in branches]
    colors = [_color_for_compliance(b.compliance.value) for b in branches]

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=120)
    ax.bar(ids, loads, color=colors, edgecolor="#2c3e50", linewidth=0.5)
    ax.axhline(80, color=COLOR_WARNING, linestyle="--",
               linewidth=0.8, label="Advertencia 80%")
    ax.axhline(100, color=COLOR_VIOLATION, linestyle=":",
               linewidth=0.8, label="Límite 100%")
    ax.set_xlabel("Branch")
    ax.set_ylabel("Cargabilidad (%)")
    ax.set_ylim(0, max(110, max(loads) + 10))
    _apply_style(ax, "Cargabilidad por elemento")
    ax.legend(fontsize=7, loc="upper right")
    plt.xticks(rotation=45, ha="right", fontsize=7)
    plt.tight_layout()
    return _save_png(fig)


# =============================================================================
# Chart 3: Hosting capacity (PV vs Carga)
# =============================================================================
def hosting_capacity_chart(hosting_results: Any) -> bytes:
    bus_list = sorted(
        hosting_results.bus_results.values(),
        key=lambda b: -b.pv_hosting_kw,
    )
    ids = [b.bus_id for b in bus_list]
    pv = [b.pv_hosting_kw for b in bus_list]
    load = [b.load_hosting_kw for b in bus_list]

    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    width = 0.4
    import numpy as np
    x = np.arange(len(ids))
    ax.bar(x - width/2, pv, width, color="#f39c12",
           label="Capacidad PV (kW)", edgecolor="#2c3e50", linewidth=0.5)
    ax.bar(x + width/2, load, width, color="#3498db",
           label="Capacidad Carga (kW)", edgecolor="#2c3e50", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(ids, rotation=45, ha="right", fontsize=7)
    ax.set_xlabel("Bus")
    ax.set_ylabel("Capacidad disponible (kW)")
    _apply_style(ax, "Host Capacity por bus (PV vs Carga adicional)")
    ax.legend(fontsize=8, loc="upper right")
    plt.tight_layout()
    return _save_png(fig)


# =============================================================================
# Chart 4: Mapa de calor — load profile 24h por bus
# =============================================================================
def heatmap_24h(profiles: dict, max_profiles: int = 8) -> bytes:
    import numpy as np
    keys = list(profiles.keys())[:max_profiles]
    matrix = []
    for k in keys:
        p = profiles[k][:24] if len(profiles[k]) >= 24 else profiles[k] + [0] * (24 - len(profiles[k]))
        matrix.append(p)
    arr = np.array(matrix)

    fig, ax = plt.subplots(figsize=(8, 0.4 * len(keys) + 1.5), dpi=120)
    im = ax.imshow(arr, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)], fontsize=7)
    ax.set_yticks(range(len(keys)))
    ax.set_yticklabels(keys, fontsize=7)
    ax.set_xlabel("Hora del día")
    _apply_style(ax, "Perfiles 24h (intensidad relativa)")
    cb = plt.colorbar(im, ax=ax, fraction=0.025)
    cb.ax.tick_params(labelsize=7)
    plt.tight_layout()
    return _save_png(fig)


# =============================================================================
# Helper interno
# =============================================================================
def _save_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
