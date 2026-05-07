# 🚢 Guía de Despliegue — `redes_engine`

Esta guía cubre el despliegue en producción de redes_engine API + Web Console
en las plataformas más comunes.

---

## 📋 Tabla de plataformas soportadas

| Plataforma | Costo demo | Tier free | Setup | URL pública |
|---|---|---|---|---|
| **Fly.io** | $0 | Sí (auto-stop) | 3 comandos | `*.fly.dev` |
| **Railway.app** | $5 crédito | Trial | 2 clics + CLI | `*.up.railway.app` |
| **Render.com** | $0 | Free tier | Blueprint YAML | `*.onrender.com` |
| **VPS propio** | $5-10/mes | — | docker-compose | dominio propio |
| **Kubernetes** | varía | — | manifest YAML | personalizado |

---

## 🟦 Opción 1 — Fly.io (recomendada para demo)

**Pros:** región Santiago de Chile (latencia baja desde Ecuador), free tier real,
auto-stop cuando no hay tráfico (cero costo si nadie la usa).

### Pre-requisitos
- Cuenta en [fly.io](https://fly.io)
- CLI `flyctl`: `iwr https://fly.io/install.ps1 -useb | iex` (Windows) o
  `curl -L https://fly.io/install.sh | sh` (Linux/Mac)

### Pasos

```bash
# 1. Login
fly auth login

# 2. Generar app (NO toca fly.toml ya existente; usa --no-deploy)
fly launch --no-deploy --copy-config --name redes-engine-demo

# 3. Deploy
fly deploy

# 4. Abrir en navegador
fly open
```

Tu URL pública aparecerá: `https://redes-engine-demo.fly.dev`.

### Configuración avanzada

```bash
# Ver logs en tiempo real
fly logs

# Escalar horizontalmente
fly scale count 2

# Aumentar memoria
fly scale memory 2048

# Volumen persistente para .rsproj
fly volumes create redes_data --size 1
# Editar fly.toml para descomentar [[mounts]]
fly deploy
```

---

## 🟪 Opción 2 — Railway.app

**Pros:** Setup más simple desde GitHub, dashboard intuitivo, $5 crédito free.

### Pasos

```bash
# 1. Login y conectar
npm i -g @railway/cli   # o usar binario de https://railway.app/cli
railway login
railway link             # selecciona tu proyecto Railway

# 2. Deploy (lee railway.toml automáticamente)
railway up

# 3. Generar dominio público
railway domain
```

URL pública: `https://redes-engine-production-xxxx.up.railway.app`.

### Variables de entorno

En el dashboard de Railway → Variables:
```
REDES_ENGINE_ENV=production
LOG_LEVEL=info
```

---

## 🟧 Opción 3 — Render.com (full free tier)

**Pros:** Blueprint YAML auto-deploy desde GitHub, 100% free para demos.
**Contras:** Tier free duerme tras 15 min sin tráfico (primer request tarda 30-60s).

### Pasos

1. Push del repo a GitHub
2. Ir a [dashboard.render.com](https://dashboard.render.com) → "New +" → "Blueprint"
3. Conectar repo → Render detecta `render.yaml` automáticamente
4. Click "Apply" → espera 5-10 minutos
5. URL pública: `https://redes-engine.onrender.com`

---

## 🟫 Opción 4 — VPS propio con Docker Compose

**Pros:** Control total, costo predecible, dominio propio, certs Let's Encrypt.
**Recomendado para producción.**

### Setup en VPS Ubuntu 22.04

```bash
# 1. SSH al VPS
ssh root@your-vps-ip

# 2. Instalar Docker
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER

# 3. Clonar repo
git clone https://github.com/your-org/redes-engine.git
cd redes-engine

# 4. Levantar con perfil producción (incluye nginx)
docker compose --profile production up -d

# 5. Configurar Let's Encrypt para HTTPS
apt install certbot python3-certbot-nginx
certbot certonly --webroot -w /var/www/html \
    -d redes-engine.tudominio.com

# 6. Copiar certs al volumen montado
mkdir -p deploy/certs
cp /etc/letsencrypt/live/redes-engine.tudominio.com/* deploy/certs/

# 7. Editar deploy/nginx.conf para descomentar bloque HTTPS
# 8. Reiniciar nginx
docker compose restart nginx
```

### Renovación automática Let's Encrypt

Crontab:
```cron
0 3 * * 0 certbot renew --post-hook "docker compose restart nginx"
```

---

## 🟨 Opción 5 — Kubernetes

Para distribuidoras con infraestructura k8s existente.

```yaml
# deploy/k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: redes-engine
spec:
  replicas: 3
  selector:
    matchLabels: { app: redes-engine }
  template:
    metadata:
      labels: { app: redes-engine }
    spec:
      containers:
      - name: api
        image: ghcr.io/your-org/redes-engine:latest
        ports: [{ containerPort: 8000 }]
        livenessProbe:
          httpGet: { path: /api/v1/health, port: 8000 }
          initialDelaySeconds: 15
        readinessProbe:
          httpGet: { path: /api/v1/health, port: 8000 }
        resources:
          requests: { memory: 512Mi, cpu: 500m }
          limits:   { memory: 2Gi, cpu: 2000m }
---
apiVersion: v1
kind: Service
metadata:
  name: redes-engine-svc
spec:
  type: ClusterIP
  selector: { app: redes-engine }
  ports: [{ port: 80, targetPort: 8000 }]
```

```bash
kubectl apply -f deploy/k8s/
kubectl get pods -l app=redes-engine
```

---

## 🐳 Imagen pre-construida desde GHCR

Una vez que el workflow `docker-publish.yml` haya corrido, la imagen está
disponible públicamente:

```bash
# Pull directo (sin clonar el repo)
docker pull ghcr.io/your-org/redes-engine:latest

docker run -p 8000:8000 ghcr.io/your-org/redes-engine:latest
```

Para usar en `docker-compose.yml` sin build:

```yaml
services:
  api:
    image: ghcr.io/your-org/redes-engine:latest   # en vez de build
    # ...
```

---

## ⚙️ Variables de entorno soportadas

| Variable | Default | Descripción |
|---|---|---|
| `REDES_ENGINE_ENV` | `production` | Modo de operación |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warning`, `error` |
| `PORT` | `8000` | Puerto interno |
| `WORKERS` | `1` | Workers uvicorn (escalado vertical) |

---

## 📊 Sizing recomendado

| Caso | CPU | RAM | Disk | Notas |
|---|---|---|---|---|
| Demo / 1 usuario | 1 vCPU | 512 MB | 1 GB | Free tier OK |
| Equipo pequeño (5-10 usr) | 2 vCPU | 1 GB | 5 GB | $5-10/mes VPS |
| Distribuidora media | 4 vCPU | 4 GB | 20 GB | Análisis 8760h con redes 100+ buses |
| Distribuidora grande | 8 vCPU | 16 GB | 100 GB | + PostgreSQL externo |

---

## 🔒 Hardening de producción

Antes de exponer a internet:

```bash
# 1. CORS restringido
# Editar redes_engine/api/main.py:
# allow_origins=["https://tu-dominio.com"]   # en vez de ["*"]

# 2. Autenticación (TODO: agregar JWT)
# Por ahora: usar nginx con auth básica o cloudflare access

# 3. Rate limiting (vía nginx)
# limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

# 4. HTTPS obligatorio (ya en deploy/nginx.conf comentado)

# 5. Backups del volumen /data
docker run --rm -v redes_data:/data -v $(pwd):/backup alpine \
    tar czf /backup/data-backup-$(date +%F).tar.gz /data
```

---

## 🩺 Monitoreo y observabilidad

### Logs estructurados

uvicorn ya emite logs en formato estándar. Para enviarlos a un agregador:

```bash
# Loki + Grafana via Promtail
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d
```

### Métricas Prometheus

(TODO: añadir endpoint `/metrics` con `prometheus-fastapi-instrumentator`)

### Healthcheck endpoint

`GET /api/v1/health` retorna:
```json
{
  "status": "ok",
  "version": "0.1.0",
  "opendss_available": true,
  "networks_count": 0
}
```

Use cualquier monitor (UptimeRobot, Healthchecks.io, Datadog) apuntando ahí.

---

## 🆘 Troubleshooting

### Container arranca pero healthcheck falla

```bash
docker compose logs api
# Buscar errores de import (opendss requiere libgomp1)
```

### Build muy lento

El primer build descarga ~500 MB de wheels (numpy, matplotlib, opendssdirect, ...).
Subsiguientes usan cache de Docker BuildKit.

### Memoria insuficiente

Análisis 8760h sobre redes grandes pueden requerir >1 GB. Aumentar tier del VM.

### Error "OpenDSS not available"

La imagen incluye `opendssdirect.py` con sus binarios para Linux x86_64.
En arquitecturas exóticas (RISC-V, etc.) puede fallar — usar la build amd64.

---

## ⚓ Soporte

- Issues: [GitHub Issues](https://github.com/your-org/redes-engine/issues)
- Email: redes-engine@example.com
