# Regenerates assets\icon-*.png and assets\auden.png.
# Run from the repository root: powershell -File build\make_icon.ps1
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "assets"
New-Item -ItemType Directory -Force $out | Out-Null

$sizes = @(256, 128, 64, 48, 32, 16)
foreach ($s in $sizes) {
    $bmp = New-Object System.Drawing.Bitmap($s, $s)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)

    $c = [float]($s / 2.0)
    $r = [float]($s * 0.47)
    $bg = New-Object System.Drawing.Drawing2D.LinearGradientBrush(
        (New-Object System.Drawing.PointF(0, 0)),
        (New-Object System.Drawing.PointF($s, $s)),
        [System.Drawing.Color]::FromArgb(255, 10, 24, 38),
        [System.Drawing.Color]::FromArgb(255, 2, 7, 12))
    $g.FillEllipse($bg, $c - $r, $c - $r, 2 * $r, 2 * $r)

    $ringWidth = [Math]::Max(1.0, $s * 0.052)
    $ring = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 55, 216, 255), $ringWidth)
    $rr = $r * 0.78
    $g.DrawEllipse($ring, $c - $rr, $c - $rr, 2 * $rr, 2 * $rr)

    $dimRing = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(110, 55, 216, 255), [Math]::Max(1.0, $s * 0.018))
    $rr2 = $r * 0.60
    $g.DrawEllipse($dimRing, $c - $rr2, $c - $rr2, 2 * $rr2, 2 * $rr2)

    $inner = $s * 0.16
    $glow = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 55, 216, 255))
    $g.FillEllipse($glow, $c - $inner, $c - $inner, 2 * $inner, 2 * $inner)
    $core = $s * 0.085
    $white = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 226, 252, 255))
    $g.FillEllipse($white, $c - $core, $c - $core, 2 * $core, 2 * $core)

    $bmp.Save((Join-Path $out "icon-$s.png"), [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose(); $bg.Dispose(); $ring.Dispose(); $dimRing.Dispose(); $glow.Dispose(); $white.Dispose()
}

Copy-Item (Join-Path $out "icon-256.png") (Join-Path $out "auden.png") -Force
Write-Host "PNG icons written to $out"
