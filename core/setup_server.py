"""Temporary first-run setup server.

Only lives while the setup window is open.  It serves ui/setup.* and exposes a
tiny JSON API backed by core.provision.  No AI model is loaded here, which keeps
the wizard usable before the engine exists.
"""
from __future__ import annotations

import json
import mimetypes
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import paths, provision
from .config import cfg, save_config
from .version import __version__

TOKEN = secrets.token_urlsafe(24)
FINISHED = threading.Event()
CANCELLED = threading.Event()
UI_DIR = paths.ui_dir()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AUDEN-Setup/2.0"

    def log_message(self, fmt, *args):
        return

    def _headers(self, code: int, ctype: str, length: int | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.end_headers()

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._headers(code, "application/json; charset=utf-8", len(body))
        self.wfile.write(body)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _guard(self) -> bool:
        origin = self.headers.get("Origin")
        if origin and "127.0.0.1" not in origin and "localhost" not in origin:
            self._json({"error": "forbidden origin"}, 403)
            return False
        if self.headers.get("X-Auden-Token") != TOKEN:
            self._json({"error": "unauthorized"}, 401)
            return False
        return True

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html", "/setup"):
            return self._index()
        if path == "/favicon.ico":
            icon = paths.assets_dir() / "auden.ico"
            if icon.is_file():
                return self._file(icon, "image/x-icon")
            self.send_response(204)
            self.end_headers()
            return
        if path.startswith("/ui/"):
            return self._static(path[4:])
        if path.startswith("/api/setup/"):
            if not self._guard():
                return
            if path == "/api/setup/scan":
                return self._json(provision.scan())
            if path == "/api/setup/status":
                return self._json(provision.status())
            return self._json({"error": "not found"}, 404)
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if not path.startswith("/api/setup/"):
            return self._json({"error": "not found"}, 404)
        if not self._guard():
            return

        if path == "/api/setup/start":
            body = self._body()
            engine = str(body.get("engine") or "auto")
            model = str(body.get("model") or provision.recommended_model(provision.scan()["ram_gb"]))
            try:
                ok = provision.start(engine, model)
            except Exception as exc:
                return self._json({"error": str(exc)}, 400)
            return self._json({"ok": ok, "status": provision.status()})
        if path == "/api/setup/finish":
            return self._finish()
        if path == "/api/setup/cancel":
            provision.cancel()
            CANCELLED.set()
            return self._json({"ok": True})
        if path == "/api/setup/cancel-download":
            provision.cancel()
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def _finish(self) -> None:
        body = self._body()
        if not provision.status_done():
            return self._json({"error": "Setup has not finished installing the AI engine."}, 400)
        name = str(body.get("name") or "").strip()[:40] or "sir"
        city = str(body.get("city") or "").strip()[:80]
        units = "imperial" if str(body.get("units") or "").lower().startswith("imp") else "metric"
        voice = bool(body.get("voice", True))
        first_run = not cfg("app", "setup_complete", default=False)
        updates = {
            "app": {"setup_complete": True, "version": __version__},
            "identity": {"user_name": name},
            "location": {"city": city, "units": units},
            "voice": {"enabled": voice},
        }
        if first_run:
            # The first HUD should open as the full console, not inherit a
            # leftover mode from an Edge profile or an old config.
            updates["ui"] = {"start_mode": "full"}
        save_config(updates)
        FINISHED.set()
        return self._json({"ok": True})

    def _index(self) -> None:
        page = (UI_DIR / "setup.html").read_text(encoding="utf-8")
        page = page.replace("__TOKEN__", TOKEN).replace("__VERSION__", __version__)
        raw = page.encode("utf-8")
        self._headers(200, "text/html; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def _static(self, rel: str) -> None:
        target = (UI_DIR / rel.replace("\\", "/")).resolve()
        if UI_DIR.resolve() not in target.parents and target != UI_DIR.resolve():
            return self._json({"error": "forbidden"}, 403)
        if not target.is_file():
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._file(target, ctype)

    def _file(self, target: Path, ctype: str) -> None:
        raw = target.read_bytes()
        self._headers(200, ctype, len(raw))
        self.wfile.write(raw)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create() -> tuple[Server, int]:
    for port in range(8766, 8786):
        try:
            httpd = Server(("127.0.0.1", port), Handler)
            return httpd, port
        except OSError:
            continue
    raise RuntimeError("No free port for the setup window.")
