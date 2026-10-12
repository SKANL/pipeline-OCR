<#
.SYNOPSIS
  Levanta MongoDB (Docker) + la API y la PWA para desarrollo local.

.DESCRIPTION
  Idempotente: verifica propietario y salud antes de reutilizar la API
  (:8000) y la PWA (:3010); solo arranca los servicios ausentes. Pensado para
  ejecutarse desde el repo de la API: `pwsh -File scripts/dev.ps1`.
#>
$ErrorActionPreference = "Stop"

$api = Split-Path -Parent $PSScriptRoot
$web = Join-Path (Split-Path -Parent $api) "biblioteca-eclesiastica-web"

if (-not (Test-Path $web)) {
  Write-Error "No se encontró la PWA en $web (repo hermano 'biblioteca-eclesiastica-web')."
}

function Test-ProjectService {
  param([int]$Port, [string]$Root, [string]$Marker, [string]$HealthUrl)

  $owners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
    Where-Object LocalPort -eq $Port | Select-Object -ExpandProperty OwningProcess -Unique)
  if ($owners.Count -eq 0) { return $false }
  $rootPattern = [regex]::Escape($Root.TrimEnd('\')) + '[\\/]'
  foreach ($ownerId in $owners) {
    $currentId = $ownerId
    $owned = $false
    # Reload workers may inherit ownership from a project-specific launcher.
    for ($depth = 0; $depth -lt 8 -and $currentId -gt 0; $depth++) {
      $process = Get-CimInstance Win32_Process -Filter "ProcessId=$currentId"
      if (-not $process) { break }
      if ($process.CommandLine -match $rootPattern -and $process.CommandLine -match $Marker) {
        $owned = $true
        break
      }
      $currentId = $process.ParentProcessId
    }
    if (-not $owned) { throw "Port $Port has an unrelated or unverifiable owner (PID $ownerId)." }
  }
  try {
    $response = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 10
    if ($response.StatusCode -ne 200) { throw "HTTP $($response.StatusCode)" }
    if ($Port -eq 8000 -and ($response.Content | ConvertFrom-Json).status -ne 'ok') {
      throw 'Unexpected API health response.'
    }
    if ($Port -eq 3010 -and $response.Content -notmatch '(?i)<html') {
      throw 'Unexpected PWA response.'
    }
  } catch { throw "Project listener on port $Port is unhealthy: $($_.Exception.Message)" }
  return $true
}

function Wait-ProjectService {
  param([int]$Port, [string]$Root, [string]$Marker, [string]$HealthUrl)
  for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 2
    if (Test-ProjectService $Port $Root $Marker $HealthUrl) { return }
  }
  throw "Service did not listen on port $Port within 60 seconds. Inspect it before retrying."
}

# Serialize launcher invocations; preflight both ports before any startup.
$mutex = [System.Threading.Mutex]::new($false, 'Local\BibliotecaAPI8000PWA3010')
$locked = $false
$oldCors = $env:CORS_ORIGINS
$oldApiBase = $env:NEXT_PUBLIC_API_BASE_URL
try {
  try { $locked = $mutex.WaitOne(0) }
  catch [System.Threading.AbandonedMutexException] { $locked = $true }
  if (-not $locked) { throw 'Another local launcher is running.' }
  $apiReady = Test-ProjectService 8000 $api 'uvicorn.*app\.main:app' 'http://localhost:8000/health'
  $webReady = Test-ProjectService 3010 $web 'next[\\/].*|next.*(?:dev|start)' 'http://localhost:3010/'

  if (-not $apiReady) {
    if (-not (docker ps --filter name=^biblio-mongo$ --format '{{.Names}}')) {
      if ($LASTEXITCODE -ne 0) { throw 'Docker is unavailable.' }
      $existing = docker ps -a --filter name=^biblio-mongo$ --format '{{.Names}}'
      if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect MongoDB container.' }
      if ($existing) { docker start biblio-mongo | Out-Null }
      else { docker run -d --name biblio-mongo -p 27017:27017 mongo:8 | Out-Null }
      if ($LASTEXITCODE -ne 0) { throw 'Cannot start MongoDB container.' }
      Start-Sleep -Seconds 4
    }
    # Process-only default takes precedence over Settings/.env; preserve explicit overrides.
    if ([string]::IsNullOrWhiteSpace($env:CORS_ORIGINS)) {
      $env:CORS_ORIGINS = 'http://localhost:3010'
    }
    Start-Process -FilePath 'uv' `
      -ArgumentList 'run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000' `
      -WorkingDirectory $api -WindowStyle Hidden
    Wait-ProjectService 8000 $api 'uvicorn.*app\.main:app' 'http://localhost:8000/health'
  }

  if (-not $webReady) {
    if (-not (Test-Path (Join-Path $web 'node_modules'))) {
      Push-Location $web
      try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed.' }
      } finally { Pop-Location }
    }
    $env:NEXT_PUBLIC_API_BASE_URL = 'http://localhost:8000'
    Start-Process -FilePath 'pwsh' `
      -ArgumentList '-NoProfile', '-Command', 'npm run dev -- -p 3010' `
      -WorkingDirectory $web -WindowStyle Hidden
    Wait-ProjectService 3010 $web 'next[\\/].*|next.*(?:dev|start)' 'http://localhost:3010/'
  }
  Write-Host 'API      -> http://localhost:8000/docs'
  Write-Host 'PWA      -> http://localhost:3010/biblioteca'
} finally {
  $env:CORS_ORIGINS = $oldCors
  $env:NEXT_PUBLIC_API_BASE_URL = $oldApiBase
  if ($locked) { $mutex.ReleaseMutex() }
  $mutex.Dispose()
}
