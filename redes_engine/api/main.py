# -*- coding: utf-8 -*-
"""
redes_engine.api.main
======================

Aplicación FastAPI principal.

Ejecutar:
    uvicorn redes_engine.api.main:app --reload --port 8000

Luego:
    Browser → http://127.0.0.1:8000
    API docs → http://127.0.0.1:8000/docs
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from .routers import analysis, assets, geojson, networks, project_io, reports
from .schemas.network import HealthOut, NetworkSummaryOut
from .storage import get_store


# =============================================================================
# Lifespan: inicialización al arrancar
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("⚡ Redes Engine API arrancando...")
    yield
    # Shutdown
    print("⚡ Redes Engine API detenido.")


# =============================================================================
# App
# =============================================================================
app = FastAPI(
    title="Redes Engine API",
    description=(
        "API REST que expone el motor redes_engine: construcción/import de redes, "
        "resolución de flujos de potencia con OpenDSS, análisis 8760h, "
        "Host Capacity y compliance ARCERNNR."
    ),
    version=__version__,
    lifespan=lifespan,
)

# CORS abierto (prototipo). Producción: restringir orígenes.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Routers
# =============================================================================
app.include_router(networks.router)
app.include_router(analysis.router)
app.include_router(geojson.router)
app.include_router(reports.router)
app.include_router(project_io.router)
app.include_router(assets.router)
app.include_router(assets.catalogs_router)


# =============================================================================
# Health
# =============================================================================
@app.get("/api/v1/health", response_model=HealthOut, tags=["meta"])
def health() -> HealthOut:
    try:
        import opendssdirect  # noqa: F401
        opendss_ok = True
    except ImportError:
        opendss_ok = False
    return HealthOut(
        status="ok",
        version=__version__,
        opendss_available=opendss_ok,
        networks_count=get_store().count(),
    )


# =============================================================================
# Endpoint demo: cargar red de Pastaza con un POST sin body
# =============================================================================
@app.post("/api/v1/demo/load",
          response_model=NetworkSummaryOut,
          tags=["demo"])
def load_demo_network() -> NetworkSummaryOut:
    """
    Carga la red de ejemplo "El Pastaza" para demos sin necesidad
    de subir archivos. Útil para pruebas y onboarding.
    """
    from ..examples.urbanizacion_mixta import build_urbanizacion_pastaza
    net = build_urbanizacion_pastaza()
    stored = get_store().create(name=net.name, network=net)
    return NetworkSummaryOut(
        id=stored.id,
        name=stored.name,
        n_buses=len(net.buses),
        n_branches=len(net.branches),
        n_assets=len(net.assets),
        n_buses_mt=sum(1 for b in net.buses.values() if b.is_mt()),
        n_buses_bt=sum(1 for b in net.buses.values() if b.is_bt()),
        total_demand_kw=net.total_load_kw(),
        total_generation_kw=net.total_generation_kw(),
        total_storage_kwh=net.total_storage_kwh(),
        is_connected=net.is_connected(),
    )


# =============================================================================
# Frontend estático
# =============================================================================
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

if os.path.isdir(_STATIC_DIR):
    app.mount(
        "/static",
        StaticFiles(directory=_STATIC_DIR),
        name="static",
    )


@app.get("/", include_in_schema=False)
def serve_index():
    index_path = os.path.join(_STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return RedirectResponse(url="/docs")


# =============================================================================
# CLI entrypoint para `redes-engine-api` después de pip install
# =============================================================================
def _run_uvicorn_cli():
    """Lanzar el servidor desde la línea de comandos."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="redes_engine API server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    uvicorn.run(
        "redes_engine.api.main:app",
        host=args.host, port=args.port,
        reload=args.reload, workers=args.workers,
    )


if __name__ == "__main__":
    _run_uvicorn_cli()
