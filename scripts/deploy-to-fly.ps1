# ─────────────────────────────────────────────────────────────────────────────
# scripts/deploy-to-fly.ps1
#
# Despliega redes-engine a Fly.io (region Santiago de Chile, free tier).
#
# Uso:
#   .\scripts\deploy-to-fly.ps1
#   .\scripts\deploy-to-fly.ps1 -AppName "mi-redes-engine"
#
# Pre-requisitos:
#   1. flyctl instalado:
#        iwr https://fly.io/install.ps1 -useb | iex
#   2. Cuenta en https://fly.io
# ─────────────────────────────────────────────────────────────────────────────

param(
    [string]$AppName = "redes-engine-demo",

    [string]$Region = "scl",      # Santiago de Chile

    [int]$MemoryMB = 1024,

    [switch]$NoDeploy,

    [switch]$WithVolume
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Deploying redes-engine to Fly.io" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  App      : $AppName"
Write-Host "  Region   : $Region (Santiago de Chile)"
Write-Host "  Memory   : ${MemoryMB} MB"
Write-Host ""

# ── 1. Verificar flyctl ────────────────────────────────────────────────────
$flyAvailable = $null -ne (Get-Command flyctl -ErrorAction SilentlyContinue)
if (-not $flyAvailable) {
    Write-Host "flyctl no encontrado. Instalando..." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Ejecuta el siguiente comando en PowerShell:" -ForegroundColor White
    Write-Host "      iwr https://fly.io/install.ps1 -useb | iex" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Luego cierra y abre nuevo PowerShell, y re-ejecuta este script."
    exit 1
}

$flyVer = flyctl version 2>&1 | Select-Object -First 1
Write-Host "  flyctl version: $flyVer" -ForegroundColor Gray

# ── 2. Verificar autenticacion ─────────────────────────────────────────────
Write-Host ""
Write-Host "[1/4] Verificando autenticacion..." -ForegroundColor Yellow
$user = flyctl auth whoami 2>&1
if ($user -match "Error" -or $LASTEXITCODE -ne 0) {
    Write-Host "      No autenticado. Ejecutando 'flyctl auth login'..." -ForegroundColor Yellow
    flyctl auth login
}
Write-Host "      Usuario: $user" -ForegroundColor Green

# ── 3. Modificar fly.toml con el AppName del usuario ──────────────────────
$flyToml = "fly.toml"
if (Test-Path $flyToml) {
    $content = Get-Content $flyToml -Raw
    $newContent = $content -replace 'app\s*=\s*"[^"]*"', "app = `"$AppName`""
    $newContent = $newContent -replace 'primary_region\s*=\s*"[^"]*"', "primary_region = `"$Region`""
    Set-Content $flyToml $newContent
}

# ── 4. Crear app si no existe ──────────────────────────────────────────────
Write-Host ""
Write-Host "[2/4] Creando/verificando app '$AppName'..." -ForegroundColor Yellow
$appInfo = flyctl status --app $AppName 2>&1
if ($appInfo -match "Could not find App|not found") {
    flyctl apps create $AppName --org personal
    if ($LASTEXITCODE -ne 0) {
        Write-Error "No se pudo crear la app. Posiblemente el nombre esta tomado, intenta con otro nombre."
        exit 1
    }
    Write-Host "      App creada: $AppName" -ForegroundColor Green
} else {
    Write-Host "      App ya existe: $AppName" -ForegroundColor Green
}

# ── 5. Volume para persistencia (opcional) ─────────────────────────────────
if ($WithVolume) {
    Write-Host ""
    Write-Host "[+] Creando volumen persistente..." -ForegroundColor Yellow
    flyctl volumes create redes_data --size 1 --region $Region --app $AppName --yes 2>&1
}

# ── 6. Deploy ──────────────────────────────────────────────────────────────
if (-not $NoDeploy) {
    Write-Host ""
    Write-Host "[3/4] Deploying (puede tardar 3-5 min en build)..." -ForegroundColor Yellow
    flyctl deploy --app $AppName --vm-memory $MemoryMB
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Deploy fallo. Revisa logs con: flyctl logs --app $AppName"
        exit 1
    }
}

# ── 7. URL final ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[4/4] Verificando URL publica..." -ForegroundColor Yellow
$url = "https://$AppName.fly.dev"
Start-Sleep -Seconds 5

$health = $null
try {
    $health = Invoke-RestMethod -Uri "$url/api/v1/health" -TimeoutSec 30
} catch {
    Write-Host "      Servicio aun no responde, esperando 10s mas..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
    try { $health = Invoke-RestMethod -Uri "$url/api/v1/health" -TimeoutSec 30 } catch {}
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  DEPLOY EXITOSO" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  URL publica :  $url"
Write-Host "  API docs    :  $url/docs"
Write-Host "  Health      :  $url/api/v1/health"
if ($health) {
    Write-Host ""
    Write-Host "  Health check OK:" -ForegroundColor Green
    $health | ConvertTo-Json -Compress | Out-Host
}
Write-Host ""
Write-Host "  Comandos utiles:"
Write-Host "      flyctl logs --app $AppName              ver logs"
Write-Host "      flyctl scale memory 2048 --app $AppName aumentar RAM"
Write-Host "      flyctl scale count 2 --app $AppName     escalar horizontal"
Write-Host "      flyctl apps destroy $AppName            eliminar app"
Write-Host ""
