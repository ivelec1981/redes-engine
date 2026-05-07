# -*- coding: utf-8 -*-
"""
redes_engine.hosting
=====================

Análisis de Host Capacity (Capacidad de Alojamiento).

Responde la pregunta crítica para distribuidoras:
    "¿Cuánto VE/PV/carga adicional puede soportar cada bus
     sin violar la normativa, considerando 8760h de operación?"

Algoritmo:
    1. Para cada bus de la red:
        - Bisección sobre el valor de potencia adicional
        - Por cada candidato, simular horas críticas
        - Detectar primer violación (voltaje, ampacidad, trafo, flujo inverso)
    2. Devolver capacidad máxima por bus + factor limitante

Optimizaciones:
    - Bisección O(log n) en vez de barrido lineal
    - Horas críticas (~100 en vez de 8760) por iteración
    - Validación final 8760h solo en el punto óptimo (opcional)

Resultado: mapa de calor de capacidad de alojamiento sobre la red.
"""

from .hosting_capacity import HostingCapacityAnalyzer
from .results import (
    BusHostingCapacity,
    HostingCapacityResults,
    LimitingFactor,
)
from .visualization import (
    hosting_ranking_table,
    write_hosting_geojson,
)

__all__ = [
    "BusHostingCapacity", "HostingCapacityResults",
    "LimitingFactor",
    "HostingCapacityAnalyzer",
    "write_hosting_geojson", "hosting_ranking_table",
]
