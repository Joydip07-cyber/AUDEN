param(
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "`n=== AUDEN build ===" -ForegroundColor Cyan

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { throw "Python was not found on PATH." }

& $python -c "import PyInstaller, psutil"
if ($LASTEXITCODE -ne 0) {
    throw "Build dependencies missing. Run: python -m pip install pyinstaller psutil"
}

if ($Clean) {
    Remove-Item "$Root\dist" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item "$Root\build\pyinstaller" -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $SkipTests) {
    Write-Host "`n[1/3] tests" -ForegroundColor Cyan
    & $python tests\test_code.py
    if ($LASTEXITCODE -ne 0) { throw "tests/test_code.py failed" }
    & $python tests\test_agent.py
    if ($LASTEXITCODE -ne 0) { throw "tests/test_agent.py failed" }
    & $python tests\test_confirm.py
    if ($LASTEXITCODE -ne 0) { throw "tests/test_confirm.py failed" }
    Remove-Item "$Root\data\tmp_test" -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "`n[2/3] freezing AUDEN.exe" -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean `
    --workpath "$Root\build\pyinstaller" `
    --distpath "$Root\dist" `
    "$Root\AUDEN.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$appDir = Join-Path $Root "dist\AUDEN"
$exe = Join-Path $appDir "AUDEN.exe"
if (-not (Test-Path $exe)) { throw "dist\AUDEN\AUDEN.exe was not produced" }

Copy-Item README.md, LICENSE, PRIVACY.md, SECURITY.md, THIRD_PARTY_NOTICES.md $appDir -Force

if (-not $SkipInstaller) {
    Write-Host "`n[3/3] building Windows installer" -ForegroundColor Cyan
    $isccCandidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) {
        throw "Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php or run with -SkipInstaller."
    }
    & $iscc "$Root\installer\AUDEN.iss"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

    $installer = Get-ChildItem "$Root\dist\installer\AUDEN-Setup-*.exe" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $installer) { throw "Installer was not produced" }

    # Optional Authenticode signing. Set both variables to enable it.
    if ($env:AUDEN_SIGN_CERT -and $env:AUDEN_SIGN_PASSWORD) {
        $signtool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
        if (-not $signtool) { $signtool = "C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe" }
        if (Test-Path $signtool) {
            Write-Host "Signing binaries..." -ForegroundColor Cyan
            & $signtool sign /f $env:AUDEN_SIGN_CERT /p $env:AUDEN_SIGN_PASSWORD `
                /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $exe
            & $signtool sign /f $env:AUDEN_SIGN_CERT /p $env:AUDEN_SIGN_PASSWORD `
                /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 $installer.FullName
        } else {
            Write-Warning "signtool.exe not found; skipping signing."
        }
    }

    $hash = (Get-FileHash $installer.FullName -Algorithm SHA256).Hash
    "$hash  $($installer.Name)" | Set-Content "$Root\dist\installer\SHA256SUMS.txt" -Encoding ascii
    Write-Host "`nInstaller: $($installer.FullName)" -ForegroundColor Green
    Write-Host "SHA256:    $hash" -ForegroundColor Green
} else {
    Write-Host "`nApp bundle: $exe" -ForegroundColor Green
}

Write-Host "`nBuild complete." -ForegroundColor Green
