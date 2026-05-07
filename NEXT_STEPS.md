# 🚀 Pasos restantes — Publicación pública

El repo está **100% listo localmente**. Solo faltan dos comandos con tus credenciales.

---

## ✅ Lo que ya está hecho

```
✅ git init + commit inicial (51cf336)
✅ 99 archivos · 17,523 líneas
✅ .gitignore + LICENSE (MIT) + CONTRIBUTING.md
✅ 189 tests pasan
✅ Ruff lint limpio
✅ Docker build verificado
✅ Workflows GitHub Actions configurados
```

---

## 📋 Paso 1 — Publicar en GitHub (~5 min)

### Opción A: Automático con `gh` CLI (recomendado)

```powershell
# Instalar gh CLI (una sola vez)
winget install --id GitHub.cli

# Autenticarse (una sola vez)
gh auth login
# → Selecciona "GitHub.com" → "HTTPS" → "Login with a web browser"

# Ejecutar el script
.\scripts\publish-to-github.ps1 -Username "TU-USUARIO" -Public
```

El script hará automáticamente:
1. Crea el repo `TU-USUARIO/redes-engine` en GitHub
2. Configura el remote `origin`
3. Push de `main`
4. Lista los runs de GitHub Actions

### Opción B: Manual (sin gh CLI)

```powershell
# 1. Crear el repo manualmente en https://github.com/new
#    - Nombre: redes-engine
#    - Visibilidad: Public
#    - NO inicializar con README

# 2. Agregar remote
git remote add origin https://github.com/TU-USUARIO/redes-engine.git

# 3. Push
git push -u origin main
```

GitHub Actions arrancará automáticamente:
- ✅ **CI**: lint + tests sobre Python 3.10/3.11/3.12
- ✅ **Docker publish**: imagen `ghcr.io/TU-USUARIO/redes-engine:latest`

---

## 🌐 Paso 2 — Deploy a Fly.io (~10 min)

### Opción A: Automático con script

```powershell
# Instalar flyctl (una sola vez)
iwr https://fly.io/install.ps1 -useb | iex

# Cierra y abre PowerShell de nuevo (PATH refresh)

# Crea cuenta gratis en https://fly.io (con tu GitHub)

# Login (una sola vez)
flyctl auth login

# Ejecutar el script
.\scripts\deploy-to-fly.ps1 -AppName "TU-NOMBRE-UNICO"
```

El script hará automáticamente:
1. Crea la app en Fly.io
2. Configura región Santiago de Chile (latencia baja desde Ecuador)
3. Build de imagen Docker en remoto
4. Deploy con healthcheck
5. Verifica `GET /api/v1/health`

**URL pública** quedará en: `https://TU-NOMBRE-UNICO.fly.dev`

### Opción B: Manual

```powershell
flyctl auth login
flyctl launch --no-deploy --copy-config --name TU-NOMBRE-UNICO
flyctl deploy
flyctl open
```

---

## 🎬 Demo a clientes / colegas

Una vez deployado, la URL queda accesible **24/7 sin costo** (Fly.io free tier
auto-stop cuando no hay tráfico, auto-start cuando llega un request).

```
https://TU-NOMBRE-UNICO.fly.dev          → Web Console MapLibre
https://TU-NOMBRE-UNICO.fly.dev/docs     → Swagger UI auto-generado
```

### Demostración típica (3 minutos)

```
1. Abrir la URL → muestra Web Console con mapa
2. Click "⚡ Cargar demo" → red Pastaza aparece
3. Click "⚡ Resolver flujo" → trafo se pinta amarillo (85% loading)
4. Click "🏠 Host Capacity" → ranking de buses
5. Click "💾 Guardar .rsproj" → descarga proyecto
```

---

## 🛠️ Tras el deploy: comandos útiles

```powershell
# Ver logs en tiempo real
flyctl logs --app TU-NOMBRE-UNICO

# Ver estado y máquinas
flyctl status --app TU-NOMBRE-UNICO

# Aumentar memoria (si análisis 8760h da OOM)
flyctl scale memory 2048 --app TU-NOMBRE-UNICO

# Escalar horizontalmente
flyctl scale count 2 --app TU-NOMBRE-UNICO

# Conectarse via SSH al container
flyctl ssh console --app TU-NOMBRE-UNICO

# Ver costo (free tier suele ser $0)
flyctl billing show

# Eliminar la app por completo
flyctl apps destroy TU-NOMBRE-UNICO
```

---

## ⚠️ Pre-deploy: cosas a editar antes

Antes de hacer público, **busca y reemplaza** estas referencias en archivos:

```powershell
# En README.md, DEPLOYMENT.md, .github/workflows/*.yml:
your-org → TU-USUARIO-GITHUB
example.com → tu-dominio.com (opcional)
```

PowerShell quick fix:
```powershell
$me = "TU-USUARIO-GITHUB"
@("README.md", "DEPLOYMENT.md") | ForEach-Object {
    (Get-Content $_) -replace 'your-org', $me | Set-Content $_
}
```

---

## 🔐 Hardening producción (si vas a clientes reales)

Antes de exponer públicamente con datos sensibles:

1. **CORS restringido** — editar `redes_engine/api/main.py`:
   ```python
   allow_origins=["https://tu-dominio.com"]   # en vez de ["*"]
   ```

2. **Autenticación** — agregar JWT (TODO en roadmap)

3. **Rate limiting** — vía nginx o Cloudflare

4. **HTTPS** — Fly.io ya lo provee gratis

5. **Backups** — del volumen `/data` con `flyctl volumes` o snapshots

Detalles completos en `DEPLOYMENT.md` sección "Hardening producción".

---

## 📊 Si sale algo mal

| Síntoma | Causa probable | Solución |
|---|---|---|
| `git push` rechazado | repo en GitHub vacío | Crear repo SIN inicializar README |
| GitHub Actions falla | Personal Access Token | Verificar permisos `packages: write` |
| Fly deploy timeout | Build tarda mucho | Aumentar `--build-only-timeout 600` |
| 502 al abrir URL | App durmiendo | Esperar 15-30 s (auto-start) |
| OOM al correr 8760h | RAM insuficiente | `flyctl scale memory 2048` |

---

## 🎯 Tras tener URL pública

1. **Editar README** con la URL real (badges, sección Quick Start)
2. **Compartir en LinkedIn / Twitter** con screenshot
3. **Enviar a CNEL/EEQ** con el caso de Pastaza
4. **Charla en ECUACIER** con demo en vivo

---

¿Listo? Ejecuta:

```powershell
.\scripts\publish-to-github.ps1 -Username TU-USUARIO -Public
.\scripts\deploy-to-fly.ps1 -AppName TU-NOMBRE-UNICO
```

⚡ **En 15 minutos tendrás URL pública.**
