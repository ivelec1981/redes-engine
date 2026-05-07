# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                     redes_engine — Production Dockerfile                  ║
# ║                                                                           ║
# ║  Build:                                                                   ║
# ║    docker build -t redes-engine:latest .                                  ║
# ║                                                                           ║
# ║  Run:                                                                     ║
# ║    docker run -p 8000:8000 redes-engine:latest                            ║
# ║                                                                           ║
# ║  Stage 1: builder con build-tools (compila wheels nativos si hace falta)  ║
# ║  Stage 2: runtime mínimo, solo lo necesario para correr                   ║
# ╚══════════════════════════════════════════════════════════════════════════╝

# ============================================================================
# STAGE 1 — BUILDER
# ============================================================================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build tools sólo en esta etapa
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copiar primero requirements para aprovechar cache de Docker
COPY requirements.txt setup.py ./
COPY redes_engine/__init__.py redes_engine/__init__.py

# Construir wheels en /wheels
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt


# ============================================================================
# STAGE 2 — RUNTIME
# ============================================================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REDES_ENGINE_ENV=production

# OpenDSS native libs requieren libgomp1; opendssdirect ya empaqueta el resto
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Usuario no-root para seguridad
RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser appuser

WORKDIR /app

# Copiar wheels pre-construidos del builder
COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels

# Copiar código de la aplicación
COPY --chown=appuser:appuser redes_engine/ ./redes_engine/
COPY --chown=appuser:appuser setup.py README.md ./

# Instalar el paquete en modo editable
RUN pip install -e . --no-deps

# Crear directorio de datos persistente (montaje en docker-compose)
RUN mkdir -p /data /app/logs && chown -R appuser:appuser /data /app/logs

USER appuser
EXPOSE 8000

# Health check para orquestadores (k8s, docker swarm)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

# Comando por defecto: 1 worker (escalado horizontal vía orquestador)
CMD ["python", "-m", "uvicorn", "redes_engine.api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--log-level", "info", "--access-log"]
