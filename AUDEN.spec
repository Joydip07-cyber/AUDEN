# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for AUDEN.

Build with:
    python -m PyInstaller --noconfirm --clean ^
        --workpath build\\pyinstaller --distpath dist AUDEN.spec
"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

a = Analysis(
    [str(ROOT / "auden.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "ui"), "ui"),
        (str(ROOT / "assets"), "assets"),
    ],
    hiddenimports=[
        "core.brain",
        "core.browser",
        "core.config",
        "core.memory",
        "core.paths",
        "core.provision",
        "core.server",
        "core.setup_server",
        "core.tools",
        "core.window",
        "psutil",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "unittest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AUDEN",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "auden.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AUDEN",
)
