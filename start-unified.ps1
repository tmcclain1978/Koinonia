# start-unified.ps1
param(
  [int]$Port = 8000,
  [string]$App = "apps.main:app"     # update if your entrypoint differs
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if (Test-Path ".\venv\Scripts\Activate.ps1") { . .\venv\Scripts\Activate.ps1 }
else {
  Write-Host "Creating venv and installing deps..."
  python -m venv venv
  . .\venv\Scripts\Activate.ps1
  pip install --upgrade pip
  pip install fastapi uvicorn[standard] flask asgiref httpx requests
}

Start-Process "http://127.0.0.1:$Port/dashboard/"
uvicorn $App --port $Port --reload
