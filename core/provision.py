"""First-run engine setup for AUDEN.

AUDEN talks to Ollama.  On a machine that already runs Ollama we simply reuse
it.  Otherwise we install a private Ollama runtime under %LOCALAPPDATA%\\AUDEN
and start it on port 11435, leaving any system Ollama untouched.  The model is
then pulled through Ollama's HTTP API so the setup page can show real progress.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import psutil

from . import paths
from .config import cfg, save_config
from .version import __version__

HOST_EXISTING = "http://127.0.0.1:11434"
HOST_PRIVATE = "http://127.0.0.1:11435"
OLLAMA_VERSION = "0.40.10"
OLLAMA_ZIP = (
    "https://github.com/ollama/ollama/releases/download/"
    f"v{OLLAMA_VERSION}/ollama-windows-amd64.zip"
)
UA = "AUDEN-Setup/2.0"
CREATE_NO_WINDOW = 0x08000000

# Verified tags from the Ollama library; sizes are approximate download sizes.
MODELS = {
    "qwen3:1.7b": {"label": "Qwen3 1.7B", "size_gb": 1.4, "ram_gb": 6,
                   "note": "Fastest. Good for 8 GB machines."},
    "qwen3:4b": {"label": "Qwen3 4B", "size_gb": 2.5, "ram_gb": 8,
                 "note": "Recommended balance of quality and speed."},
    "qwen3:8b": {"label": "Qwen3 8B", "size_gb": 5.2, "ram_gb": 16,
                 "note": "Best answers. Needs 16 GB RAM and patience."},
}

_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$")

_lock = threading.Lock()
_state: dict = {
    "stage": "idle",
    "percent": 0,
    "message": "Waiting to start.",
    "done": False,
    "error": "",
    "host": "",
    "model": "",
    "downloaded": 0,
    "total": 0,
}
_thread: threading.Thread | None = None
_started_proc: subprocess.Popen | None = None
_started_private = False
_started_log = None
_cancel = threading.Event()


def _set(**updates) -> None:
    with _lock:
        _state.update(updates)


def status() -> dict:
    with _lock:
        return dict(_state)


def status_done() -> bool:
    with _lock:
        return bool(_state["done"] and not _state["error"])


def reset() -> None:
    with _lock:
        _state.update({
            "stage": "idle", "percent": 0, "message": "Waiting to start.",
            "done": False, "error": "", "host": "", "model": "",
            "downloaded": 0, "total": 0,
        })
    _cancel.clear()


def cancel() -> None:
    """Ask the provisioning worker to stop at the next safe point."""
    _cancel.set()


def _get_json(host: str, path: str, timeout: float = 3.0):
    req = urllib.request.Request(host.rstrip("/") + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe(host: str, timeout: float = 2.0) -> dict | None:
    try:
        data = _get_json(host, "/api/tags", timeout=timeout)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def models_on(host: str) -> dict[str, int]:
    data = probe(host)
    out: dict[str, int] = {}
    if not data:
        return out
    for item in data.get("models") or []:
        name = str(item.get("name") or "")
        if name:
            out[name] = int(item.get("size") or 0)
    return out


def _known_paths() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    pf = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
    pf86 = Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")
    return [
        local / "Programs" / "Ollama" / "ollama.exe",
        pf / "Ollama" / "ollama.exe",
        pf86 / "Ollama" / "ollama.exe",
    ]


def find_installed() -> str:
    for path in _known_paths():
        if path.is_file():
            return str(path)
    found = shutil.which("ollama")
    return found or ""


def runtime_exe() -> str:
    root = paths.runtime_dir()
    direct = root / "ollama.exe"
    if direct.is_file():
        return str(direct)
    if root.is_dir():
        try:
            for candidate in root.rglob("ollama.exe"):
                return str(candidate)
        except OSError:
            pass
    return ""


def recommended_model(ram_gb: float) -> str:
    if ram_gb < 7.5:
        return "qwen3:1.7b"
    if ram_gb < 15.0:
        return "qwen3:4b"
    return "qwen3:8b"


def _current_model(models: dict[str, int]) -> str:
    wanted = str(cfg("brain", "model", default="") or "")
    if wanted and wanted in models:
        return wanted
    if not models:
        return ""
    # Fresh config but an existing Ollama: reuse something already on disk
    # rather than silently downloading several gigabytes. Prefer instruct
    # models, then the smallest, and skip embedding-only models.
    usable = [
        name for name in models
        if not any(word in name.lower() for word in ("embed", "minilm", "bge-"))
    ] or list(models)
    usable.sort(key=lambda name: models.get(name, 0))
    for name in usable:
        if "instruct" in name.lower():
            return name
    return usable[0]


def scan() -> dict:
    existing = probe(HOST_EXISTING)
    models = models_on(HOST_EXISTING) if existing else {}
    installed = find_installed()
    private = runtime_exe()
    mem = psutil.virtual_memory()
    ram_gb = round(mem.total / 2 ** 30, 1)
    try:
        free_gb = round(shutil.disk_usage(str(Path.home())).free / 2 ** 30, 1)
    except Exception:
        free_gb = 0.0

    current = _current_model(models)
    model_list = []
    for tag, meta in MODELS.items():
        model_list.append({
            "tag": tag,
            "label": meta["label"],
            "size_gb": meta["size_gb"],
            "ram_gb": meta["ram_gb"],
            "note": meta["note"],
            "installed": tag in models,
            "recommended": not current and tag == recommended_model(ram_gb),
        })
    if current and current not in MODELS:
        size = round(models.get(current, 0) / 2 ** 30, 1)
        model_list.insert(0, {
            "tag": current,
            "label": current.split(":")[0],
            "size_gb": size,
            "ram_gb": 8,
            "note": "Already installed on this PC.",
            "installed": True,
            "recommended": True,
        })

    return {
        "version": __version__,
        "ram_gb": ram_gb,
        "free_gb": free_gb,
        "existing_ollama": bool(existing),
        "existing_models": sorted(models),
        "installed_exe": installed,
        "private_runtime": private,
        "private_ready": bool(private),
        "recommended": recommended_model(ram_gb),
        "current_model": current,
        "models": model_list,
        "setup_complete": bool(cfg("app", "setup_complete", default=False)),
        "engine_choices": [
            {
                "id": "auto",
                "label": "Automatic (recommended)",
                "detail": "Use Ollama if it is already running, otherwise install a private copy.",
                "available": True,
            },
            {
                "id": "existing",
                "label": "Use the Ollama on this PC",
                "detail": f"Found at {installed}" if installed else "No existing Ollama found.",
                "available": bool(installed or existing),
            },
            {
                "id": "private",
                "label": "Install a private AUDEN engine",
                "detail": f"Download Ollama {OLLAMA_VERSION} into AUDEN's own folder.",
                "available": True,
            },
        ],
    }


def _download(url: str, dest: Path, stage: str, lo: int, hi: int) -> None:
    """Download with HTTP Range resume; updates the global setup progress."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.is_file() else 0
    headers = {"User-Agent": UA}
    if have:
        headers["Range"] = f"bytes={have}-"

    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except Exception:
        if not have:
            raise
        have = 0
        try:
            part.unlink()
        except OSError:
            pass
        resp = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60)

    with resp:
        code = getattr(resp, "status", 200)
        if have and code != 206:
            have = 0
            try:
                part.unlink()
            except OSError:
                pass
        total = have + int(resp.headers.get("Content-Length") or 0)
        if code == 206:
            content_range = resp.headers.get("Content-Range") or ""
            m = re.search(r"/(\d+)$", content_range)
            if m:
                total = int(m.group(1))
        _set(stage=stage, downloaded=have, total=total,
             message=f"Downloading Ollama {OLLAMA_VERSION} ({total / 2**30:.1f} GB)..." if total else
                     f"Downloading Ollama {OLLAMA_VERSION}...")
        with open(part, "ab" if have else "wb") as fh:
            done = have
            while True:
                if _cancel.is_set():
                    raise RuntimeError("Setup cancelled.")
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                pct = lo + (hi - lo) * (done / total if total else 0)
                _set(percent=int(pct), downloaded=done, total=total,
                     message=f"Downloading Ollama runtime... {done / 2**30:.2f} GB"
                             + (f" of {total / 2**30:.2f} GB" if total else ""))
    if dest.exists():
        dest.unlink()
    part.replace(dest)


def install_runtime() -> str:
    exe = runtime_exe()
    if exe:
        return exe
    if _cancel.is_set():
        raise RuntimeError("Setup cancelled.")

    target = paths.runtime_dir()
    target.mkdir(parents=True, exist_ok=True)
    zip_path = Path(tempfile.gettempdir()) / f"auden-ollama-{OLLAMA_VERSION}.zip"

    valid = False
    if zip_path.is_file():
        try:
            with zipfile.ZipFile(zip_path) as zf:
                valid = zf.testzip() is None
        except Exception:
            valid = False
    if not valid:
        _download(OLLAMA_ZIP, zip_path, "runtime", 5, 35)

    _set(stage="runtime", percent=36, message="Unpacking the local AI engine...")
    work = Path(tempfile.mkdtemp(prefix="auden-runtime-"))
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(work)
        found = None
        for candidate in work.rglob("ollama.exe"):
            found = candidate
            break
        if not found:
            raise RuntimeError("The Ollama archive did not contain ollama.exe.")
        source_root = found.parent
        shutil.copytree(source_root, target, dirs_exist_ok=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    exe = runtime_exe()
    if not exe:
        raise RuntimeError("Ollama was unpacked but ollama.exe could not be found.")
    try:
        zip_path.unlink()
    except OSError:
        pass
    return exe


def _port(host: str) -> int:
    try:
        return int(urllib.parse.urlparse(host).port or 11434)
    except Exception:
        return 11434


def _tail(path: Path, limit: int = 1200) -> str:
    try:
        data = path.read_bytes()[-limit:]
        return data.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def start_server(exe: str, host: str, private: bool = False) -> bool:
    """Start ollama serve for ``host`` and wait until /api/tags answers."""
    global _started_proc, _started_private, _started_log
    if probe(host):
        return True
    if not exe or not Path(exe).is_file():
        return False

    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"127.0.0.1:{_port(host)}"
    env["OLLAMA_KEEP_ALIVE"] = "30m"
    if private:
        env["OLLAMA_MODELS"] = str(paths.models_dir())
        env["OLLAMA_ORIGINS"] = "http://127.0.0.1:*"
    log_path = paths.logs_dir() / "ollama.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _started_log = open(log_path, "ab", buffering=0)
    except Exception:
        _started_log = None

    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        _started_proc = subprocess.Popen(
            [exe, "serve"],
            cwd=str(Path(exe).parent),
            env=env,
            stdout=_started_log or subprocess.DEVNULL,
            stderr=subprocess.STDOUT if _started_log else subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        _started_private = private
    except Exception:
        return False

    deadline = time.time() + 90
    while time.time() < deadline:
        if _cancel.is_set():
            stop_server()
            return False
        if probe(host, timeout=1.5):
            return True
        if _started_proc.poll() is not None:
            break
        time.sleep(0.5)
    stop_server()
    return False


def stop_server() -> None:
    """Stop the Ollama process AUDEN started (never a pre-existing one)."""
    global _started_proc, _started_private, _started_log
    proc, _started_proc = _started_proc, None
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    if _started_log is not None:
        try:
            _started_log.close()
        except Exception:
            pass
    _started_log = None
    _started_private = False


def _pull(host: str, model: str, lo: int, hi: int) -> None:
    body = json.dumps({"name": model, "stream": True}).encode("utf-8")
    req = urllib.request.Request(
        host.rstrip("/") + "/api/pull",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST",
    )
    layers: dict[str, tuple[int, int]] = {}
    last_status = ""
    with urllib.request.urlopen(req, timeout=120) as resp:
        for raw in resp:
            if _cancel.is_set():
                raise RuntimeError("Setup cancelled.")
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except Exception:
                continue
            if data.get("error"):
                raise RuntimeError(str(data["error"]))
            status_text = str(data.get("status") or "")
            if status_text:
                last_status = status_text
            digest = str(data.get("digest") or "")
            total = int(data.get("total") or 0)
            completed = int(data.get("completed") or 0)
            if digest and total:
                layers[digest] = (completed, total)
            if layers:
                done = sum(v[0] for v in layers.values())
                size = sum(v[1] for v in layers.values())
                pct = lo + (hi - lo) * (done / size if size else 0)
                _set(percent=int(pct), downloaded=done, total=size,
                     message=f"{last_status or 'Downloading model'}... "
                             f"{done / 2**30:.2f} GB of {size / 2**30:.2f} GB")
            elif last_status:
                _set(percent=max(lo, _state["percent"]),
                     message=f"{last_status}...")
    if model not in models_on(host):
        raise RuntimeError(f"The model {model} was not registered after download.")


def _validate_model(model: str) -> str:
    model = (model or "").strip()
    if not _MODEL_RE.match(model):
        raise ValueError("Invalid model name.")
    return model


def start(engine: str = "auto", model: str = "qwen3:4b") -> bool:
    global _thread
    engine = (engine or "auto").lower()
    if engine not in {"auto", "existing", "private"}:
        return False
    model = _validate_model(model)
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
    reset()
    _thread = threading.Thread(target=_provision, args=(engine, model), daemon=True)
    _thread.start()
    return True


def _provision(engine: str, model: str) -> None:
    try:
        _set(stage="engine", percent=2, message="Checking for Ollama on this PC...")
        host = ""
        if engine != "private":
            if probe(HOST_EXISTING):
                host = HOST_EXISTING
                _set(percent=12, message="Using the Ollama already running on this PC.")
            elif engine in {"auto", "existing"}:
                installed = find_installed()
                if installed:
                    _set(percent=8, message="Starting the Ollama already installed on this PC...")
                    if start_server(installed, HOST_EXISTING, private=False):
                        host = HOST_EXISTING
        if not host and engine == "existing":
            raise RuntimeError(
                "No existing Ollama installation was found. Choose the automatic option instead."
            )

        if not host:
            _set(stage="runtime", percent=4, message="Preparing AUDEN's private AI engine...")
            if runtime_exe():
                _set(percent=35, message="Found AUDEN's private engine.")
            else:
                _set(percent=5, message=f"Downloading Ollama {OLLAMA_VERSION}...")
                install_runtime()
            _set(percent=37, message="Starting the local AI engine...")
            if not start_server(runtime_exe(), HOST_PRIVATE, private=True):
                detail = _tail(paths.logs_dir() / "ollama.log")
                raise RuntimeError("The local AI engine did not start." + (f"\n{detail}" if detail else ""))
            host = HOST_PRIVATE

        # A fresh private Ollama has an empty model list; that is exactly the
        # case where we need to pull the selected model.  Do not treat an
        # empty list as a failed engine.
        models = models_on(host)
        if model not in models:
            _set(stage="model", percent=40,
                 message=f"Downloading {model} (~{MODELS.get(model, {}).get('size_gb', 2)} GB). "
                         "This is the largest step.")
            _pull(host, model, 40, 94)
        _set(stage="final", percent=96, message="Saving configuration...")
        save_config({
            "app": {"version": __version__},
            "brain": {
                "provider": "ollama",
                "host": host,
                "model": model,
                "fallback_models": [model],
            },
        })
        _set(stage="done", percent=100, done=True, host=host, model=model,
             message="The AI engine is ready.")
    except Exception as exc:
        _set(stage="error", error=str(exc)[:800],
             message="Setup could not finish.")
        stop_server()


def ensure_engine() -> bool:
    """Make the configured host reachable, starting Ollama if necessary."""
    host = str(cfg("brain", "host", default=HOST_EXISTING) or HOST_EXISTING)
    if probe(host):
        return True
    port = _port(host)
    exe = runtime_exe() if port == _port(HOST_PRIVATE) else find_installed()
    if not exe:
        exe = find_installed() or runtime_exe()
    if not exe or not Path(exe).is_file():
        return False
    private = runtime_exe() and Path(exe).resolve() == Path(runtime_exe()).resolve()
    return start_server(exe, host, private=bool(private))


def shutdown() -> None:
    _cancel.set()
    stop_server()
