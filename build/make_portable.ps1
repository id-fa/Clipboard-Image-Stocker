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
    $zipName = "dist/Stocker-v$version-win64.zip"
    if (Test-Path $zipName) { Remove-Item $zipName }
    Compress-Archive -Path "dist/Stocker/*" -DestinationPath $zipName

    Write-Host "Built portable zip: $zipName"
    (Get-Item $zipName).Length / 1MB | ForEach-Object { Write-Host ("Size: {0:N1} MB" -f $_) }
}
finally {
    Pop-Location
}
