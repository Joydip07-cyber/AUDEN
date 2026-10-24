"""Filesystem layout for source runs and the installed app.

Source checkout
    <repo>/config.json
    <repo>/data/          (database, screenshots, window profile)

Installed app (PyInstaller one-folder, per-user)
    <install>/AUDEN.exe
    <install>/_internal/ui/
    %LOCALAPPDATA%/AUDEN/config.json
    %LOCALAPPDATA%/AUDEN/auden.db
    %LOCALAPPDATA%/AUDEN/models/
    %LOCALAPPDATA%/AUDEN/runtime/
    %LOCALAPPDATA%/AUDEN/logs/

Portable
    Put a file called ``portable.txt`` next to AUDEN.exe. Config, data and
    models then live beside the executable instead of in %LOCALAPPDATA%.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "AUDEN"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_portable() -> bool:
    if os.environ.get("AUDEN_PORTABLE") == "1":
        return True
    try:
        return (executable_dir() / "portable.txt").is_file()
    except Exception:
        return False


def executable_dir() -> Path:
    """Folder containing AUDEN.exe (or the repository root in source runs)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Folder containing bundled read-only assets (ui/, assets/)."""
    # PyInstaller one-folder places data files in _internal and sets _MEIPASS.
    return Path(getattr(sys, "_MEIPASS", executable_dir()))


def home_dir() -> Path:
    """Writable application home: config, models and runtime."""
    override = os.environ.get("AUDEN_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen() and not is_portable():
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / APP_NAME
    return executable_dir()


def data_dir() -> Path:
    """Database and transient data."""
    if is_frozen() and not is_portable():
        return home_dir()
    return executable_dir() / "data"


def config_path() -> Path:
    return home_dir() / "config.json"


def ui_dir() -> Path:
    return resource_dir() / "ui"


def assets_dir() -> Path:
    return resource_dir() / "assets"


def models_dir() -> Path:
    return home_dir() / "models"


def runtime_dir() -> Path:
    return home_dir() / "runtime"


def logs_dir() -> Path:
    return data_dir() / "logs"


def workspace_dir() -> Path:
    """Default folder for files AUDEN creates."""
    if is_frozen():
        return Path.home() / "Documents" / APP_NAME
    return executable_dir()


def ensure() -> None:
    for folder in (data_dir(), logs_dir(), data_dir() / "screenshots"):
        folder.mkdir(parents=True, exist_ok=True)
    if is_frozen():
        workspace_dir().mkdir(parents=True, exist_ok=True)
