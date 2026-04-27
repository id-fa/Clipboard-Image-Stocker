# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Stocker. Run from project root:
    pyinstaller --clean build/stocker.spec
"""

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH is provided by PyInstaller
SRC = ROOT / "src"

a = Analysis(
    [str(ROOT / "src" / "stocker" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        (str(ROOT / "src" / "stocker" / "db" / "schema.sql"), "stocker/db"),
        (str(ROOT / "src" / "stocker" / "db" / "migrations"), "stocker/db/migrations"),
    ],
    hiddenimports=[],
    excludes=[
        "tkinter",
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtBluetooth",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtPositioning",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DAnimation",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Stocker",
    icon=None,  # set to "assets/icons/app.ico" once you add one
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Stocker",
)
