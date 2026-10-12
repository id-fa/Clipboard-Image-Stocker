#!/usr/bin/env pwsh
# Build a portable zip distribution.
# Usage:  .\build\make_portable.ps1
$ErrorActionPreference = "Stop"

Push-Location (Join-Path $PSScriptRoot "..")
try {
    if (Test-Path "dist/Stocker") {
        Remove-Item -Recurse -Force "dist/Stocker"
    }
    & .\.venv\Scripts\pyinstaller.exe --clean build/stocker.spec
    if ($LASTEXITCODE -ne 0) {
        throw "pyinstaller failed (exit $LASTEXITCODE)"
    }

    # Drop a portable.flag so the app stores config under dist/Stocker/userdata
    New-Item -ItemType File -Path "dist/Stocker/portable.flag" -Force | Out-Null

    # Read version from pyproject.toml
    $version = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value

    # ---- License files (LGPLv3 compliance for PySide6/Qt + attributions) ----
    # PySide6 wheels ship only the commercial-license reference, so the
    # LGPL/GPL texts are kept in build/licenses/. Pillow / Python / PyInstaller
    # texts are copied from the venv so they always match the bundled versions.
    $licDir = "dist/Stocker/licenses"
    New-Item -ItemType Directory -Path $licDir -Force | Out-Null
    Copy-Item LICENSE "dist/Stocker/LICENSE.txt"
    Copy-Item build/licenses/LGPL-3.0.txt $licDir
    Copy-Item build/licenses/GPL-3.0.txt $licDir

    $py = ".\.venv\Scripts\python.exe"
    $sitePkgs = & $py -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
    $basePrefix = & $py -c "import sys; print(sys.base_prefix)"
    $ver = @{}
    (& $py -c @"
import sys, PySide6, shiboken6, PIL, PyInstaller
from PySide6.QtCore import qVersion
print('PYSIDE6_VERSION=' + PySide6.__version__)
print('SHIBOKEN6_VERSION=' + shiboken6.__version__)
print('QT_VERSION=' + qVersion())
print('PILLOW_VERSION=' + PIL.__version__)
print('PYINSTALLER_VERSION=' + PyInstaller.__version__)
print('PYTHON_VERSION=' + sys.version.split()[0])
"@) | ForEach-Object { $k, $v = $_ -split "=", 2; $ver[$k] = $v }

    function Copy-DistInfoLicense([string]$pkgGlob, [string]$fileName, [string]$dest) {
        $src = Get-ChildItem -Path (Join-Path $sitePkgs $pkgGlob) -Directory |
            ForEach-Object { Join-Path $_.FullName "licenses/$fileName" } |
            Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $src) { throw "license file not found: $pkgGlob/licenses/$fileName" }
        Copy-Item $src (Join-Path $licDir $dest)
    }
    Copy-DistInfoLicense "pillow-*.dist-info" "LICENSE" "Pillow-LICENSE.txt"
    Copy-DistInfoLicense "pyinstaller-*.dist-info" "COPYING.txt" "PyInstaller-COPYING.txt"
    Copy-Item (Join-Path $basePrefix "LICENSE.txt") (Join-Path $licDir "Python-LICENSE.txt")

    $notice = Get-Content build/licenses/THIRD_PARTY_NOTICES.template.txt -Raw
    $notice = $notice.Replace("{APP_VERSION}", $version).Replace("{BUILD_DATE}", (Get-Date -Format "yyyy-MM-dd"))
    foreach ($k in $ver.Keys) { $notice = $notice.Replace("{$k}", $ver[$k]) }
    $leftover = [regex]::Matches($notice, "\{[A-Z0-9_]+\}") | ForEach-Object { $_.Value }
    if ($leftover) { throw "unresolved placeholders in notice: $($leftover -join ', ')" }
    [System.IO.File]::WriteAllText(
        (Join-Path (Get-Location) "$licDir/THIRD_PARTY_NOTICES.txt"),
        $notice, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "License files: dist/Stocker/LICENSE.txt + $licDir ($((Get-ChildItem $licDir).Count) files)"
    $zipName = "dist/Stocker-v$version-win64.zip"
    if (Test-Path $zipName) { Remove-Item $zipName }
    Compress-Archive -Path "dist/Stocker/*" -DestinationPath $zipName

    Write-Host "Built portable zip: $zipName"
    (Get-Item $zipName).Length / 1MB | ForEach-Object { Write-Host ("Size: {0:N1} MB" -f $_) }
}
finally {
    Pop-Location
}
