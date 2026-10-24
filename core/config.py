"""Configuration loading for AUDEN.

A single config.json at the project root is deep-merged over sane defaults so
users can edit only the keys they care about.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from . import paths
from .version import __version__

BASE_DIR = paths.executable_dir()
RESOURCE_DIR = paths.resource_dir()
DATA_DIR = paths.data_dir()
CONFIG_PATH = paths.config_path()

_HOME = Path.home()
_WORKSPACE = paths.workspace_dir()
if paths.is_frozen():
    _WRITE_ROOTS = [
        str(_WORKSPACE),
        str(_HOME / "Desktop"),
        str(_HOME / "Documents"),
        str(_HOME / "Downloads"),
        str(Path(os.environ.get("TEMP", _HOME))),
    ]
else:
    _WRITE_ROOTS = [
        str(BASE_DIR),
        str(_HOME / "Desktop"),
        str(_HOME / "Documents"),
        str(Path(os.environ.get("TEMP", _HOME))),
    ]

DEFAULTS: dict = {
    "app": {
        "setup_complete": False,
        "version": __version__,
        "update_repo": "",
        "idle_timeout": 1800,
    },
    "identity": {
        "assistant_name": "AUDEN",
        "user_name": "sir",
        "persona": (
            "You are AUDEN, a dry-witted British AI butler and systems assistant. "
            "You are calm, precise, quietly loyal and occasionally sardonic. "
            "Address the user as 'sir'. Never mention being a language model."
        ),
    },
    "brain": {
        "provider": "ollama",
        "host": "http://127.0.0.1:11434",
        "model": "qwen3:4b",
        "fallback_models": ["qwen3:4b", "qwen2.5:3b", "llama3.2:3b", "llama3.2:1b"],
        "tool_mode": "auto",
        "temperature": 0.55,
        "num_ctx": 2048,
        "max_tokens": 320,
        "keep_alive": "30m",
        "core_tools_only": True,
        "auto_fallback": False,
        "openai": {"base_url": "http://127.0.0.1:1234/v1", "api_key": "local", "model": ""},
    },
    "voice": {
        "enabled": True,
        "lang": "en-GB",
        "preferred_voices": ["Ryan", "George", "Daniel"],
        "rate": 1.04,
        "pitch": 0.86,
        "volume": 1.0,
    },
    "wake": {"enabled": True, "words": ["auden"], "require_wake_word": False},
    "safety": {
        "allow_shell": True,
        "confirm_tools": ["run_command", "write_file", "lock_pc"],
        "workspace": str(_WORKSPACE),
        "write_roots": _WRITE_ROOTS,
        "read_anywhere": True,
    },
    "ui": {"start_mode": "full", "accent": "#37d8ff", "greet_on_start": True},
    "location": {"city": "", "units": "metric"},
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict:
    override: dict = {}
    if CONFIG_PATH.exists():
        try:
            override = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:  # malformed json should not kill the app
            print(f"[config] could not parse config.json ({exc}); using defaults")
    return _deep_merge(DEFAULTS, override)


CONFIG = load_config()


def cfg(*keys, default=None):
    """Read a nested config value: cfg('brain', 'model')."""
    node = CONFIG
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def save_config(updates: dict) -> dict:
    global CONFIG
    CONFIG = _deep_merge(CONFIG, updates)
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
        tmp.write_text(json.dumps(CONFIG, indent=2), encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
    except Exception as exc:
        print(f"[config] save failed: {exc}")
    return CONFIG


def setup_complete() -> bool:
    return bool(cfg("app", "setup_complete", default=False))


paths.ensure()
