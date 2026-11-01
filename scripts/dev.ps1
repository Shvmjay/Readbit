# Run Readbit locally with one command (Windows PowerShell 5.1+ or PowerShell 7). No database server, Redis,
# Docker or API key needed.
#
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1           install, build, start, open the browser
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Reset    same, with an empty local database
#
# Optional: -ApiPort 8000 -WebPort 3000 -NoOpen. Data lives in .data\local (git-ignored). Ctrl+C stops both servers.
param(
  [switch]$Reset,
  [switch]$NoOpen,
  [int]$ApiPort = 8000,
  [int]$WebPort = 3000
)
# "Continue", not "Stop": in Windows PowerShell 5.1, "Stop" turns ordinary stderr output from native tools
# (py, pip, npm) into fatal errors. Every native step below checks $LASTEXITCODE explicitly instead.
$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root "services\api"
$WebDir = Join-Path $Root "apps\web"
$DataDir = Join-Path $Root ".data\local"

function Say($msg) { Write-Host "[readbit] $msg" -ForegroundColor Magenta }
function Die($msg) { Write-Host "[readbit] $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------- prerequisites
$Py = $null
foreach ($candidate in @("py -3.13", "py -3.12", "py -3.11", "python", "python3")) {
  $parts = $candidate.Split(" ")
  if (-not (Get-Command $parts[0] -ErrorAction SilentlyContinue)) { continue }
  $args2 = @($parts | Select-Object -Skip 1) + @("-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)")
  & $parts[0] @args2 2>$null
  if ($LASTEXITCODE -eq 0) { $Py = $parts; break }
}
if (-not $Py) { Die "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH')." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Die "Node.js 20 or newer is required. Install it from https://nodejs.org/" }
$nodeMajor = [int]((node -p "process.versions.node.split('.')[0]").Trim())
if ($nodeMajor -lt 20) { Die "Node.js 20 or newer is required (found $(node --version)). Install it from https://nodejs.org/" }

function Test-PortFree([int]$port) {
  $client = New-Object System.Net.Sockets.TcpClient
  try { $client.Connect("127.0.0.1", $port); return $false } catch { return $true } finally { $client.Dispose() }
}
function Get-FreePort([int]$start) {
  for ($p = $start; $p -lt $start + 20; $p++) { if (Test-PortFree $p) { return $p } }
  Die "No free port found near $start."
}
$p = Get-FreePort $ApiPort; if ($p -ne $ApiPort) { Say "Port $ApiPort is busy; using $p for the API." }; $ApiPort = $p
$p = Get-FreePort $WebPort; if ($p -ne $WebPort) { Say "Port $WebPort is busy; using $p for the web app." }; $WebPort = $p

if ($Reset -and (Test-Path $DataDir)) { Say "Resetting local data in $DataDir"; Remove-Item -Recurse -Force $DataDir }
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

# ---------------------------------------------------------------- API dependencies
$Venv = Join-Path $ApiDir ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
  Say "Creating Python environment (first run only)..."
  $venvArgs = @($Py | Select-Object -Skip 1) + @("-m", "venv", $Venv)
  & $Py[0] @venvArgs
  if ($LASTEXITCODE -ne 0) { Die "Creating the Python environment failed." }
}
$Stamp = Join-Path $Venv ".readbit-installed"
$Pyproject = Join-Path $ApiDir "pyproject.toml"
if (-not (Test-Path $Stamp) -or (Get-Item $Pyproject).LastWriteTime -gt (Get-Item $Stamp).LastWriteTime) {
  Say "Installing API dependencies (first run takes a few minutes)..."
  & $VenvPy -m pip install --quiet --upgrade pip
  Push-Location $ApiDir
  try { & $VenvPy -m pip install --quiet -e ".[dev]" } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { Die "Installing API dependencies failed (see the error above)." }
  New-Item -ItemType File -Force -Path $Stamp | Out-Null
}

# ---------------------------------------------------------------- web dependencies + build
$Lock = Join-Path $WebDir "package-lock.json"
$InstalledLock = Join-Path $WebDir "node_modules\.package-lock.json"
if (-not (Test-Path $InstalledLock) -or (Get-Item $Lock).LastWriteTime -gt (Get-Item $InstalledLock).LastWriteTime) {
  Say "Installing web dependencies (first run takes a few minutes)..."
  Push-Location $WebDir
  try { $env:npm_config_update_notifier = "false"; npm ci --no-audit --no-fund --loglevel=error --silent } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { Die "Installing web dependencies failed (see the error above)." }
}
$BuildId = Join-Path $WebDir ".next\BUILD_ID"
$needBuild = -not (Test-Path $BuildId)
if (-not $needBuild) {
  $built = (Get-Item $BuildId).LastWriteTime
  $sources = @("app", "components", "features", "lib", "hooks", "locales") | ForEach-Object { Join-Path $WebDir $_ }
  $newer = Get-ChildItem -Recurse -File -Path $sources | Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1
  $needBuild = [bool]$newer -or ((Get-Item (Join-Path $WebDir "package.json")).LastWriteTime -gt $built)
}
if ($needBuild) {
  Say "Building the web app..."
  $BuildLog = Join-Path $DataDir "build.log"
  Push-Location $WebDir
  try { $env:NEXT_TELEMETRY_DISABLED = "1"; npm run build *> $BuildLog } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { Get-Content $BuildLog -Tail 30; Die "The web build failed (full log: $BuildLog)." }
}

# ---------------------------------------------------------------- start
$WebUrl = "http://localhost:$WebPort"
$ApiLog = Join-Path $DataDir "api.log"
$WebLog = Join-Path $DataDir "web.log"
$DbPath = (Join-Path $DataDir "readbit.db") -replace "\\", "/"

# Child processes inherit these; they are restored when the script exits.
$saved = @{}
$apiEnv = @{
  APP_ENV = "development"; DATABASE_URL = "sqlite:///$DbPath"; STORAGE_PROVIDER = "local"
  STORAGE_LOCAL_PATH = (Join-Path $DataDir "storage"); JOB_BACKEND = "thread"
  DEFAULT_LLM_PROVIDER = $(if ($env:DEFAULT_LLM_PROVIDER) { $env:DEFAULT_LLM_PROVIDER } else { "extractive" })
  APP_URL = $WebUrl; CORS_ORIGINS = "$WebUrl,http://127.0.0.1:$WebPort"; EMAIL_DELIVERY = "log"
  LOG_LEVEL = $(if ($env:LOG_LEVEL) { $env:LOG_LEVEL } else { "WARNING" })
  API_URL = "http://127.0.0.1:$ApiPort"; PORT = "$WebPort"; NEXT_TELEMETRY_DISABLED = "1"
}
foreach ($k in $apiEnv.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $apiEnv[$k]) }

function Wait-Url($url, $name, $log, $proc) {
  for ($i = 0; $i -lt 90; $i++) {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri $url | Out-Null; return } catch { }
    if ($proc.HasExited) { if (Test-Path $log) { Get-Content $log -Tail 30 }; Die "The $name stopped unexpectedly (full log: $log)." }
    Start-Sleep -Seconds 1
  }
  if (Test-Path $log) { Get-Content $log -Tail 30 }; Die "The $name did not start within 90 seconds (full log: $log)."
}

$api = $null; $web = $null
try {
  Say "Starting the API on port $ApiPort..."
  $api = Start-Process -FilePath $VenvPy -WorkingDirectory $ApiDir -PassThru -NoNewWindow `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
    -RedirectStandardOutput $ApiLog -RedirectStandardError "$ApiLog.err"
  Wait-Url "http://127.0.0.1:$ApiPort/health" "API" "$ApiLog.err" $api

  Say "Starting the web app on port $WebPort..."
  $nextBin = Join-Path $WebDir "node_modules\next\dist\bin\next"
  $web = Start-Process -FilePath "node" -WorkingDirectory $WebDir -PassThru -NoNewWindow `
    -ArgumentList @("`"$nextBin`"", "start", "-p", "$WebPort") `
    -RedirectStandardOutput $WebLog -RedirectStandardError "$WebLog.err"
  Wait-Url "http://127.0.0.1:$WebPort/" "web app" "$WebLog.err" $web

  Write-Host ""
  Write-Host "  Readbit is running:  $WebUrl" -ForegroundColor Green
  Write-Host ""
  Write-Host "  Sample books to upload: $(Join-Path $Root 'evals\fixtures')"
  Write-Host "  Logs: $ApiLog(.err) and $WebLog(.err)"
  Write-Host "  Press Ctrl+C to stop."
  Write-Host ""
  if (-not $NoOpen) { Start-Process $WebUrl }

  while (-not $api.HasExited -and -not $web.HasExited) { Start-Sleep -Seconds 2 }
  Say "A server stopped; see the logs in $DataDir."
}
finally {
  Say "Stopping Readbit..."
  foreach ($proc in @($web, $api)) {
    if ($proc -and -not $proc.HasExited) {
      & taskkill /PID $proc.Id /T /F 2>$null | Out-Null
      if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
    }
  }
  foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
}
