# -*- coding: utf-8 -*-
"""
redes_engine.api
=================

API REST FastAPI que expone TODOS los módulos del motor:
    - Construcción/import de redes
    - Resolución de flujos de potencia (OpenDSS)
    - Análisis 8760h (timeseries)
    - Host Capacity Analysis
    - Compliance ARCERNNR
    - Exportación GeoJSON para mapa web

Endpoints principales:
    POST  /api/v1/networks               crear red desde GeoJSON
    GET   /api/v1/networks               listar redes
    GET   /api/v1/networks/{id}          obtener detalle
    POST  /api/v1/networks/{id}/solve    resolver flujo de potencia
    POST  /api/v1/networks/{id}/hosting  análisis hosting capacity
    POST  /api/v1/networks/{id}/timeseries  análisis 8760h
    GET   /api/v1/networks/{id}/geojson  topología como GeoJSON
    GET   /api/v1/networks/{id}/results/geojson  resultados pintados

Frontend estático servido en:
    GET   /                              HTML + MapLibre

Uso:
    uvicorn redes_engine.api.main:app --reload
    Browse: http://127.0.0.1:8000
"""

from .main import app

__all__ = ["app"]
