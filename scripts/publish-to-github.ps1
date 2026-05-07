# ─────────────────────────────────────────────────────────────────────────────
# scripts/publish-to-github.ps1
#
# Publica el repo local en GitHub.
#
# Uso:
#   .\scripts\publish-to-github.ps1 -Username "<tu-usuario-github>" `
#                                    -RepoName "redes-engine" `
#                                    -Public
#
# Pre-requisitos:
#   1. Estar autenticado: git config user.name "..." && git config user.email "..."
#   2. Tener `gh` CLI instalado y autenticado:
#        winget install --id GitHub.cli
#        gh auth login
#      O alternativa: tener un Personal Access Token (clásico) con scope `repo`.
# ─────────────────────────────────────────────────────────────────────────────

param(
    [Parameter(Mandatory=$true)]
    [string]$Username,

    [string]$RepoName = "redes-engine",

    [string]$Description = "Motor open-source para redes electricas de distribucion: grafo unificado MT+BT+VE+BESS, OpenDSS, 8760h, host capacity, ARCERNNR, FastAPI+MapLibre.",

    [switch]$Private,

    [switch]$SkipPush
)

$ErrorActionPreference = "Stop"

$visibility = if ($Private) { "private" } else { "public" }

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Publishing redes-engine to GitHub" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  User       : $Username"
Write-Host "  Repo       : $RepoName"
Write-Host "  Visibility : $visibility"
Write-Host ""

# ── 1. Verificar git ────────────────────────────────────────────────────────
if (-not (Test-Path .git)) {
    Write-Error "No estamos en un repo git. Ejecuta este script desde la raiz."
    exit 1
}

$head = git rev-parse HEAD 2>$null
if (-not $head) {
    Write-Error "No hay commits todavia. Haz git commit primero."
    exit 1
}
Write-Host "  Current HEAD: $head" -ForegroundColor Gray

# ── 2. Crear repo via gh CLI si esta disponible ─────────────────────────────
$ghAvailable = $null -ne (Get-Command gh -ErrorAction SilentlyContinue)

if ($ghAvailable) {
    Write-Host ""
    Write-Host "[1/2] Creando repo en GitHub via gh CLI..." -ForegroundColor Yellow

    $existing = gh repo view "$Username/$RepoName" 2>$null
    if ($existing) {
        Write-Host "      Repo ya existe: https://github.com/$Username/$RepoName" -ForegroundColor Green
    } else {
        $visFlag = if ($Private) { "--private" } else { "--public" }
        gh repo create "$Username/$RepoName" $visFlag --description $Description --source=. --remote=origin
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Fallo creando el repo"
            exit 1
        }
        Write-Host "      Repo creado: https://github.com/$Username/$RepoName" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "[1/2] gh CLI no encontrado — paso manual:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Opcion A: instalar gh CLI"
    Write-Host "      winget install --id GitHub.cli"
    Write-Host "      gh auth login"
    Write-Host "      Re-ejecuta este script"
    Write-Host ""
    Write-Host "  Opcion B: crear el repo manualmente"
    Write-Host "      1. Ir a https://github.com/new"
    Write-Host "      2. Nombre: $RepoName"
    Write-Host "      3. Visibilidad: $visibility"
    Write-Host "      4. NO inicializar con README (ya existe)"
    Write-Host "      5. Click 'Create repository'"
    Write-Host ""
    $confirm = Read-Host "Repo creado? (y/N)"
    if ($confirm -ne "y") { exit 0 }

    # Configurar remote manualmente
    $remoteUrl = "https://github.com/$Username/$RepoName.git"
    $existingRemote = git remote get-url origin 2>$null
    if ($existingRemote) {
        Write-Host "      Remote 'origin' ya configurado: $existingRemote"
    } else {
        git remote add origin $remoteUrl
        Write-Host "      Remote 'origin' configurado: $remoteUrl" -ForegroundColor Green
    }
}

# ── 3. Push ────────────────────────────────────────────────────────────────
if (-not $SkipPush) {
    Write-Host ""
    Write-Host "[2/2] Empujando commits a GitHub..." -ForegroundColor Yellow
    git push -u origin main
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Push fallo. Verifica credenciales y permisos."
        exit 1
    }
}

# ── 4. Listar GitHub Actions runs ──────────────────────────────────────────
if ($ghAvailable -and -not $SkipPush) {
    Write-Host ""
    Write-Host "[+] Verificando GitHub Actions..." -ForegroundColor Yellow
    Start-Sleep -Seconds 4
    gh run list --limit 5 --repo "$Username/$RepoName" 2>&1
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  PUBLICACION EXITOSA" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  URL repo : https://github.com/$Username/$RepoName"
Write-Host "  CI runs  : https://github.com/$Username/$RepoName/actions"
Write-Host "  Image    : ghcr.io/$Username/$RepoName"
Write-Host ""
Write-Host "  Siguiente paso: deploy a Fly.io"
Write-Host "      .\scripts\deploy-to-fly.ps1"
Write-Host ""
