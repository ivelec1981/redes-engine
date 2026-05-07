# ⚡ redes_engine

> **Motor open-source para diseño, simulación y operación de redes eléctricas de distribución.**
> Grafo unificado MT+BT+Trafo+VE+BESS · Análisis 8760h · Host Capacity · Compliance ARCERNNR · Reportes ejecutivos PDF/Word · API REST + Web Console.

[![CI](https://github.com/your-org/redes-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/redes-engine/actions/workflows/ci.yml)
[![Docker](https://github.com/your-org/redes-engine/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/your-org/redes-engine/actions/workflows/docker-publish.yml)
[![Tests](https://img.shields.io/badge/tests-189%20passing-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-yellow)]()
[![OpenDSS](https://img.shields.io/badge/engine-OpenDSS%20%2F%20EPRI-orange)]()

---

## 🎯 ¿Qué problema resuelve?

Los ingenieros de distribución eléctrica en Latinoamérica trabajan con:
- 🟥 **Hojas de Excel dispersas** — cada cálculo en un archivo distinto
- 🟥 **Software propietario costoso** — ETAP/CYMDIST cuestan $20K-$50K/licencia
- 🟥 **Cajas negras** — fórmulas no auditables ante regulador
- 🟥 **Modelos por separado** — MT, BT, soterrado, VE: redes desconectadas

**`redes_engine` resuelve esto con un grafo unificado, código abierto y normativa ecuatoriana embebida.**

---

## 🚀 Quick Start

### 🐳 Local con Docker — 1 comando

```bash
git clone https://github.com/<your-org>/redes-engine.git
cd redes-engine
docker compose up
```

Abre el navegador en **http://localhost:8000**:
- Web Console interactiva con MapLibre
- API REST documentada en **http://localhost:8000/docs** (Swagger UI)
- Botón "⚡ Cargar demo" → red de ejemplo de El Pastaza lista para analizar

### ☁ Deploy a la nube

| Plataforma | Comando | URL pública |
|---|---|---|
| **Fly.io** ⭐ | `fly launch && fly deploy` | `*.fly.dev` |
| **Railway** | `railway up` | `*.up.railway.app` |
| **Render** | Conectar repo en dashboard | `*.onrender.com` |
| **VPS propio** | `docker compose --profile production up -d` | dominio propio + HTTPS |

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template?template=https%3A%2F%2Fgithub.com%2Fyour-org%2Fredes-engine)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2Fyour-org%2Fredes-engine)

Guía completa de despliegue en [`DEPLOYMENT.md`](DEPLOYMENT.md) (todas las plataformas + Kubernetes + hardening producción).

### 📦 Imagen pre-construida (sin clonar el repo)

```bash
docker pull ghcr.io/<your-org>/redes-engine:latest
docker run -p 8000:8000 ghcr.io/<your-org>/redes-engine:latest
```

---

## ✨ Capacidades

| Capacidad | Descripción |
|---|---|
| 🕸️ **Grafo unificado** | MT + BT + Trafo + Soterrado en una misma topología |
| ⚡ **Flujo de potencia** | Bridge real con OpenDSS (motor EPRI) |
| 🛡️ **Compliance ARCERNNR** | Reg. 002/20 · evaluación automática de violaciones |
| ⏱️ **Análisis 8760h** | Año completo con perfiles realistas Ecuador |
| 🏠 **Host Capacity** | "¿Cuánto VE/PV soporta cada bus?" — bisección + horas críticas |
| 🔋 **Smart BESS dispatch** | Peak shaving + MILP daily |
| 🚗 **Smart EV charging** | MILP optimization minimizando costo TOU |
| 📍 **GIS bidireccional** | Importa GeoJSON/Shapefile/GeoPackage · Exporta a QGIS con QML |
| 📄 **Reportes ejecutivos** | PDF firmable (ReportLab) + Word editable (python-docx) |
| 📚 **Catálogos reales** | 10 cargadores VE + 10 BESS (Tesla, ABB, BYD, CATL, ...) |
| 💾 **Persistencia `.rsproj`** | JSON versionable en Git |
| 🌐 **API REST** | 25+ endpoints + OpenAPI auto-docs |
| 🖥️ **Web Console** | Editor visual + simbología en mapa |

---

## 🏗️ Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                      USUARIO / CLIENTE                          │
│            QGIS Plugin · Web Browser · CLI · Python script     │
└──────────────────────┬──────────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
         ▼             ▼             ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Plugin v1   │ │  REST API    │ │  Python lib  │
│  + adapter   │ │  (FastAPI)   │ │  directa     │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │
       └────────────────┴────────────────┘
                        │
                        ▼
       ┌────────────────────────────────────┐
       │       redes_engine (motor)         │
       ├────────────────────────────────────┤
       │  core/      grafo unificado        │
       │  io/        OpenDSS · QGIS · GIS   │
       │  timeseries 8760h + dispatch BESS  │
       │  hosting    capacity por bus       │
       │  catalogs   productos comerciales  │
       │  persistence .rsproj                │
       │  reports    PDF + Word + charts    │
       └─────────────┬──────────────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
┌───────────────┐         ┌────────────────┐
│  OpenDSS      │         │  PuLP (CBC)    │
│  flow solver  │         │  MILP solver   │
└───────────────┘         └────────────────┘
```

---

## 📦 Instalación

### Opción A: Docker (recomendado)

```bash
docker compose up           # desarrollo
docker compose --profile production up -d   # con nginx
```

### Opción B: Pip directo

```bash
# Instalación completa con todas las features
pip install -e ".[all]"

# Lanzar el API
redes-engine-api --host 0.0.0.0 --port 8000

# O directamente
python -m uvicorn redes_engine.api.main:app --reload
```

### Opción C: Solo el motor (uso programático)

```bash
pip install -e ".[opendss,milp]"   # mínimo para análisis
```

---

## 🎬 Ejemplos rápidos

### 1. Construir y resolver una red

```python
from redes_engine import Network, Bus, Branch, Asset
from redes_engine import VoltageLevel, BusType, BranchType, AssetType
from redes_engine.io.opendss_solver import OpenDSSSolver
from redes_engine.core.compliance import ARCERNNR_EC, ComplianceAnalyzer

net = Network("MiRed")

# Construir grafo (ver examples/urbanizacion_mixta.py)
# ...

# Resolver flujo de potencia
with OpenDSSSolver(net) as solver:
    solver.solve()
    result = solver.collect_results()

# Validar normativa
report = ComplianceAnalyzer(ARCERNNR_EC).analyze(result)
print(report.summary())
```

### 2. Análisis temporal 8760h con BESS smart dispatch

```python
from redes_engine.timeseries import (
    TimeSeriesSolver, ProfileLibrary, Scenario,
)
from redes_engine.examples.urbanizacion_mixta import build_urbanizacion_pastaza

net = build_urbanizacion_pastaza()
profiles = ProfileLibrary.ecuador_default()

# Aplicar escenario futuro: 50% VE en 2030
Scenario(name="2030", year=2030, ev_penetration_pct=50).apply_to_network(net, profiles)

# BESS reactivo: peak shaving (reduce trafo de 97% a 71%)
solver = TimeSeriesSolver(net, profiles=profiles, dispatch_mode="peak_shaving")
annual = solver.run(hours=8760, scenario_name="2030 con BESS")

print(annual.summary())
print(annual.violation_table())
```

### 3. Host Capacity por bus

```python
from redes_engine.hosting import HostingCapacityAnalyzer

analyzer = HostingCapacityAnalyzer(net)
results = analyzer.analyze_all(
    include_pv=True, include_load=True,
    n_critical_hours=80, max_kw=200, tolerance_kw=2,
)
print(results.ranking_table())
# → Bus_010: PV 50 kW (limita: thermal_line)
```

### 4. Generar reporte ejecutivo PDF

```python
from datetime import datetime
from redes_engine.reports import ReportContext, generate_pdf_report

ctx = ReportContext(
    title="Análisis red El Pastaza",
    project_name="El Pastaza Etapa 2",
    company_name="CNEL EP — Unidad Pastaza",
    author_name="Ing. Juan Pérez",
    author_id="SENESCYT 1234567890",
    document_code="ER-2026-001",
    network=net, flow_result=result,
    compliance_report=report,
    annual_results=annual,
)
generate_pdf_report(ctx, "reporte_ejecutivo.pdf")
# → 100 KB PDF firmable, listo SERCOP
```

### 5. Importar desde QGIS / GeoJSON

```python
from redes_engine.io.gis_importer import GISImporter

net, report = GISImporter().from_geojson({
    "postes_mt":       "postes.geojson",
    "tramos_mt":       "tramos.geojson",
    "transformadores": "trafos.geojson",
    "cargas":          "cargas.geojson",
})
print(report.summary())
```

---

## 🌐 API REST

Documentación interactiva auto-generada en **`/docs`** (Swagger UI).

### Endpoints principales

| Método | Path | Función |
|---|---|---|
| `GET`    | `/api/v1/health` | health check |
| `POST`   | `/api/v1/networks` | crear desde GeoJSON |
| `POST`   | `/api/v1/demo/load` | cargar red demo Pastaza |
| `GET`    | `/api/v1/networks/{id}` | detalle |
| `POST`   | `/api/v1/networks/{id}/solve` | resolver flujo |
| `POST`   | `/api/v1/networks/{id}/hosting` | host capacity |
| `POST`   | `/api/v1/networks/{id}/timeseries` | análisis 8760h |
| `POST`   | `/api/v1/networks/{id}/report` | PDF/Word ejecutivo |
| `POST`   | `/api/v1/networks/{id}/assets` | añadir asset (con catálogo) |
| `DELETE` | `/api/v1/networks/{id}/assets/{aid}` | eliminar asset |
| `GET`    | `/api/v1/catalogs/ev_chargers` | catálogo cargadores VE |
| `GET`    | `/api/v1/catalogs/bess` | catálogo BESS |
| `POST`   | `/api/v1/projects/save/{id}` | descargar `.rsproj` |
| `POST`   | `/api/v1/projects/load` | cargar `.rsproj` |
| `GET`    | `/api/v1/networks/{id}/results/geojson` | mapa pintado |

### Ejemplo curl

```bash
# Cargar demo, resolver, descargar PDF
NID=$(curl -sX POST http://localhost:8000/api/v1/demo/load | jq -r .id)
curl -X POST http://localhost:8000/api/v1/networks/$NID/solve
curl -X POST http://localhost:8000/api/v1/networks/$NID/report \
     -H "Content-Type: application/json" \
     -d '{"format":"pdf","author_name":"Ing. X"}' \
     --output reporte.pdf
```

---

## 🗺️ Web Console

```
http://localhost:8000
```

- **Mapa MapLibre** centrado en Ecuador
- **Modo edición**: clic en bus → modal "Agregar Asset" con catálogo
- **Botones de análisis**: ⚡ Resolver · 🏠 Hosting · ⏱ 24h
- **Exportar/Importar** `.rsproj` (proyectos versionables)
- **Simbología automática**: postes ●verde/🟡/🔴 · líneas con grosor por carga

---

## 🔌 Integración con QGIS (plugin v1)

Si ya usa el plugin QGIS **Redes Suite v1**, el adapter no-invasivo añade
una pestaña *"🔥 Análisis Integral"* que llama a `redes_engine` por debajo:

```
1. Plugins → Redes Suite → Botón "RED"
2. Pestaña "🔥 Análisis Integral"
3. [🔍 Detectar capas activas] → muestra postes/tramos/trafos detectados
4. [▶ Ejecutar análisis integral] → corre todo el pipeline
5. Mapa se pinta automáticamente con resultados
```

Detalles en [`redes_suite/adapter/README.md`](../redes_suite/adapter/README.md).

---

## 📚 Estructura del paquete

```
redes_engine/
├── core/         # graph + network + compliance + optimization (MILP)
├── io/           # opendss + gis_importer + qgis_writer
├── timeseries/   # 8760h + perfiles Ecuador + dispatch BESS
├── hosting/      # capacidad por bus
├── catalogs/     # productos comerciales (Tesla, ABB, BYD, ...)
├── persistence/  # formato .rsproj
├── reports/      # PDF + Word + charts matplotlib
├── api/          # FastAPI + frontend MapLibre
└── examples/     # 8 ejemplos end-to-end
```

---

## ⚙️ Desarrollo

### Tests

```bash
pytest tests/ -v
# 189 passed in 10.74s
```

### Lint

```bash
ruff check redes_engine/
```

### Run dev server con hot-reload

```bash
python -m uvicorn redes_engine.api.main:app --reload --port 8000
```

### Build & push imagen Docker

```bash
docker build -t redes-engine:0.1.0 .
docker tag redes-engine:0.1.0 your-registry/redes-engine:latest
docker push your-registry/redes-engine:latest
```

---

## 📊 Benchmarks medidos

| Operación | Red 8 buses | Tiempo | Notas |
|---|---|---|---|
| Solve flujo de potencia | 8 buses | ~0.05 s | OpenDSS converge en 2 iteraciones |
| Análisis 8760h | 8 buses | ~28 s | ~3 ms por hora |
| Host Capacity (8 buses, 50 hr crit) | 8 buses | ~0.4 s | Bisección con 86 iteraciones totales |
| Generación PDF reporte | — | ~2 s | 110 KB, 8 páginas con charts |
| MILP dispatch 24h | 3 BESS | ~0.5 s | CBC solver |

A escala distribuidora típica (1000 buses): el análisis 8760h escala linealmente (~6 min). El host capacity ~50 s.

---

## 🛣️ Roadmap

### Hecho ✅
- [x] Bridge OpenDSS bidireccional
- [x] Importador GIS (GeoJSON/Shapefile/GeoPackage)
- [x] Visualización QGIS automática (QML)
- [x] Adapter plugin Redes Suite v1
- [x] Análisis temporal 8760h con perfiles Ecuador
- [x] Smart dispatch BESS (peak_shaving + MILP)
- [x] Host Capacity Analysis por bus
- [x] Web App FastAPI + MapLibre
- [x] Catálogos comerciales (Tesla/ABB/BYD/CATL/...)
- [x] Perfiles taxi/bus/flota
- [x] Persistencia `.rsproj`
- [x] Editor visual interactivo
- [x] Reportes ejecutivos PDF + Word

### Pendiente 🔵
- [ ] CI/CD GitHub Actions
- [ ] Imagen Docker en Docker Hub público
- [ ] Demo público hospedado (Railway/Fly.io)
- [ ] Caso de estudio white paper para CNEL/EEQ
- [ ] Multi-tenant + autenticación JWT
- [ ] Base de datos PostgreSQL/PostGIS
- [ ] Análisis de contingencias N-1
- [ ] LLM-assisted design (Claude API)

---

## 🤝 Contribuciones

PRs son bienvenidos. Reglas básicas:

1. Tests pasan: `pytest tests/`
2. Sin warnings de lint: `ruff check`
3. Cobertura ≥ 80% para código nuevo
4. Documentación de funciones públicas (docstring)

---

## 📄 Licencia

MIT — uso libre comercial y privado, sin garantía.

---

## 🙏 Créditos

- **OpenDSS / EPRI** — motor de flujo de potencia (LICENCIA propia EPRI)
- **PuLP** — interfaz a CBC para MILP
- **MapLibre GL JS** — visualización de mapas
- **FastAPI** — framework REST
- **ReportLab + python-docx** — generadores de documentos
- **shapely** — operaciones geométricas
- **CNEL EP, EEQ, EEASA, ARCERNNR** — normativa Ecuador

---

## 📬 Contacto

- **Issues / bugs**: [GitHub Issues](https://github.com/<your-org>/redes-engine/issues)
- **Email**: redes-engine@example.com

---

<p align="center">
  <i>⚡ Built with Python, OpenDSS, and ❤️ from Ecuador</i>
</p>
