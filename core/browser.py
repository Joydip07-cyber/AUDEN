"""Locate and drive the browser the user actually uses.

Windows already knows the answer in the registry:

    HKCU\\Software\\Microsoft\\Windows\\Shell\\Associations\\
        UrlAssociations\\https\\UserChoice  ->  ProgId
    HKCR\\<ProgId>\\shell\\open\\command      ->  executable

We resolve that instead of assuming Chrome or Edge. Brave, for example, is
usually a per-user install under %LOCALAPPDATA%, so it is not on PATH.
"""
from __future__ import annotations

import os
import subprocess
import winreg
from pathlib import Path

# Chromium browsers can host the HUD with --app; Firefox cannot.
APP_MODE_BROWSERS = {"Brave", "Google Chrome", "Microsoft Edge", "Vivaldi", "Opera"}

_FAMILIES = (
    ("brave", "Brave"),
    ("chrome", "Google Chrome"),
    ("msedge", "Microsoft Edge"),
    ("firefox", "Mozilla Firefox"),
    ("vivaldi", "Vivaldi"),
    ("opera", "Opera"),
    ("yandex", "Yandex Browser"),
)

_ALIASES = {
    "brave": "Brave",
    "brave browser": "Brave",
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "google": "Google Chrome",
    "edge": "Microsoft Edge",
    "ms edge": "Microsoft Edge",
    "microsoft edge": "Microsoft Edge",
    "firefox": "Mozilla Firefox",
    "mozilla": "Mozilla Firefox",
    "vivaldi": "Vivaldi",
    "opera": "Opera",
    "yandex": "Yandex Browser",
}

_FALLBACK_ORDER = (
    "Brave",
    "Google Chrome",
    "Microsoft Edge",
    "Mozilla Firefox",
    "Vivaldi",
    "Opera",
)

_LOCAL = Path(os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"))
_PF = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
_PF86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))

_KNOWN = {
    "Brave": (
        _LOCAL / r"BraveSoftware\Brave-Browser\Application\brave.exe",
        _PF / r"BraveSoftware\Brave-Browser\Application\brave.exe",
        _PF86 / r"BraveSoftware\Brave-Browser\Application\brave.exe",
    ),
    "Google Chrome": (
        _PF / r"Google\Chrome\Application\chrome.exe",
        _PF86 / r"Google\Chrome\Application\chrome.exe",
        _LOCAL / r"Google\Chrome\Application\chrome.exe",
    ),
    "Microsoft Edge": (
        _PF86 / r"Microsoft\Edge\Application\msedge.exe",
        _PF / r"Microsoft\Edge\Application\msedge.exe",
    ),
    "Mozilla Firefox": (
        _PF / r"Mozilla Firefox\firefox.exe",
        _PF86 / r"Mozilla Firefox\firefox.exe",
    ),
    "Vivaldi": (
        _LOCAL / r"Vivaldi\Application\vivaldi.exe",
        _PF / r"Vivaldi\Application\vivaldi.exe",
    ),
    "Opera": (
        _LOCAL / r"Programs\Opera\opera.exe",
        _PF / r"Opera\opera.exe",
        _PF86 / r"Opera\opera.exe",
    ),
}


def _user_choice(scheme: str) -> str:
    path = (
        r"Software\Microsoft\Windows\Shell\Associations"
        r"\UrlAssociations\%s\UserChoice" % scheme
    )
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            return str(winreg.QueryValueEx(key, "ProgId")[0])
    except OSError:
        return ""


def _command_exe(prog_id: str) -> str:
    if not prog_id:
        return ""
    try:
        command = winreg.QueryValue(
            winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command"
        )
    except OSError:
        return ""
    command = (command or "").strip()
    if not command:
        return ""
    if command.startswith('"'):
        end = command.find('"', 1)
        exe = command[1:end] if end > 0 else ""
    else:
        exe = command.split(" ", 1)[0]
    return exe if exe and Path(exe).is_file() else ""


def _family(prog_id: str) -> str:
    low = (prog_id or "").lower()
    for prefix, name in _FAMILIES:
        if low.startswith(prefix):
            return name
    return ""


def _canonical(name: str) -> str:
    return _ALIASES.get((name or "").strip().lower(), "")


def _installed(name: str) -> str:
    for path in _KNOWN.get(name, ()):
        if path.is_file():
            return str(path)
    return ""


def _info(name: str, exe: str, prog_id: str = "") -> dict:
    return {
        "name": name,
        "exe": exe,
        "prog_id": prog_id,
        "app_mode": name in APP_MODE_BROWSERS,
    }


def detect() -> dict | None:
    """Return the default browser as {name, exe, prog_id, app_mode}."""
    for scheme in ("https", "http"):
        prog_id = _user_choice(scheme)
        if not prog_id:
            continue
        family = _family(prog_id)
        exe = _command_exe(prog_id) or _installed(family)
        if exe:
            return _info(family or Path(exe).stem, exe, prog_id)

    # No usable UserChoice (fresh profile, broken association): pick an
    # installed browser so "open browser" still does something sensible.
    for name in _FALLBACK_ORDER:
        exe = _installed(name)
        if exe:
            return _info(name, exe)
    return None


def describe() -> str:
    info = detect()
    if not info:
        return "no browser detected"
    return f"{info['name']} ({info['exe']})"


def chromium_exe(prefer_edge: bool = True) -> str:
    """Executable for a Chromium browser that can host --app windows."""
    order = (
        ("Microsoft Edge", "Brave", "Google Chrome", "Vivaldi", "Opera")
        if prefer_edge
        else ("Brave", "Google Chrome", "Microsoft Edge", "Vivaldi", "Opera")
    )
    for name in order:
        exe = _installed(name)
        if exe:
            return exe
    return ""


def open_url(url: str) -> str:
    """Open a URL in the detected browser and return its name."""
    info = detect()
    if info:
        subprocess.Popen([info["exe"], url], close_fds=True)
        return info["name"]
    os.startfile(url)  # type: ignore[attr-defined]
    return "the default browser"


def launch(name: str = "") -> str:
    """Launch a browser, or the default one. Returns its name or ''."""
    wanted = _canonical(name) if name else ""
    if name and not wanted:
        return ""
    if wanted:
        exe = _installed(wanted)
        if not exe:
            current = detect()
            if current and current["name"] == wanted:
                exe = current["exe"]
        if not exe:
            return ""
        subprocess.Popen([exe], close_fds=True)
        return wanted

    info = detect()
    if not info:
        return ""
    subprocess.Popen([info["exe"]], close_fds=True)
    return info["name"]
