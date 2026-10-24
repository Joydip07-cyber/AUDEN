# Imports a local GGUF (e.g. an LM Studio download) into Ollama instantly.
# No internet required once Ollama itself is installed.
#
#   powershell -ExecutionPolicy Bypass -File import-models.ps1
#   powershell -ExecutionPolicy Bypass -File import-models.ps1 -Path "C:\path\model.gguf" -Name "my-model"

param(
    [string]$Path = "",
    [string]$Name = ""
)

$ErrorActionPreference = "Continue"

function Test-Ollama {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 | Out-Null
        return $true
    } catch { return $false }
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "  ! Ollama is not installed. Run install.bat first." -ForegroundColor Red
    exit 1
}

if (-not (Test-Ollama)) {
    Write-Host "  .. starting Ollama service" -ForegroundColor DarkGray
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 700
        if (Test-Ollama) { break }
    }
}

# ---------------------------------------------------------------- discover
if (-not $Path) {
    $roots = @(
        "$env:USERPROFILE\.lmstudio\models",
        "$env:USERPROFILE\.cache\lm-studio\models",
        "$env:LOCALAPPDATA\LM-Studio\models"
    ) | Where-Object { Test-Path $_ }

    $candidates = @()
    foreach ($root in $roots) {
        $candidates += Get-ChildItem -Path $root -Filter *.gguf -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Length -gt 800MB -and
                $_.Name -notmatch "mmproj|embed|encoder" -and
                $_.Name -notmatch "\.part$"
            }
    }

    if (-not $candidates) {
        Write-Host "  ! No local GGUF models found." -ForegroundColor Yellow
        Write-Host "    Pull one instead:  ollama pull qwen2.5:3b"
        exit 1
    }

    # Prefer 3-4B instruct models: best quality that still runs comfortably in 8 GB RAM.
    $best = $candidates | Sort-Object @{ Expression = {
                $n = $_.Name.ToLower()
                if ($n -match "qwen3-4b|qwen3.*4b") { 0 }
                elseif ($n -match "qwen2\.5-3b|llama.*3b|phi.*3") { 1 }
                elseif ($n -match "7b|8b") { 2 }
                elseif ($n -match "1\.5b|1b|0\.5b") { 3 }
                else { 2 }
            } }, @{ Expression = { $_.Length } } | Select-Object -First 1

    $Path = $best.FullName
    Write-Host "  found $($best.Name)  ($([math]::Round($best.Length/1GB,2)) GB)" -ForegroundColor DarkCyan
}

if (-not (Test-Path $Path)) {
    Write-Host "  ! File not found: $Path" -ForegroundColor Red
    exit 1
}

if (-not $Name) {
    $Name = ($Path | Split-Path -Leaf) -replace "\.gguf$", "" -replace "[^a-zA-Z0-9\.\-]", "-"
    $Name = ($Name.ToLower() -replace "-{2,}", "-").Trim("-")
}

# ---------------------------------------------------------------- import
$modelFile = Join-Path $env:TEMP "auden-Modelfile"
@"
FROM "$($Path -replace '\\', '/')"
PARAMETER num_ctx 4096
PARAMETER temperature 0.55
"@ | Set-Content -Path $modelFile -Encoding ASCII

Write-Host "  importing as '$Name' (copies the weights into Ollama's store)..." -ForegroundColor DarkGray
& ollama create $Name -f $modelFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "  ! Import failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "  ok  model ready: $Name" -ForegroundColor Green
Write-Host ('  set  "brain": { "model": "' + $Name + '" }  in config.json') -ForegroundColor Gray
Write-Host ""
& ollama list
