"""Local HTTP + SSE server for the AUDEN HUD.

Deliberately dependency-free (stdlib only) so the app runs on a bare Python
install. Bound to 127.0.0.1 and guarded by a per-launch session token.
"""
from __future__ import annotations

import json
import mimetypes
import queue
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil

from . import memory, paths, tools, window as win
from .brain import Brain
from .config import CONFIG, save_config

UI_DIR = paths.ui_dir()
TOKEN = secrets.token_urlsafe(24)
STARTED = time.time()

BRAIN = Brain()
SUBSCRIBERS: list[queue.Queue] = []
SUB_LOCK = threading.Lock()
CONFIRM_LOCK = threading.Lock()
CONFIRM_EVENTS: dict[str, dict] = {}
SHUTDOWN = threading.Event()


class ClientGone(Exception):
    pass


def broadcast(event: dict) -> None:
    with SUB_LOCK:
        for q in list(SUBSCRIBERS):
            try:
                q.put_nowait(event)
            except Exception:
                pass


tools.set_notifier(broadcast)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def telemetry() -> dict:
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home().anchor or "C:\\"))
        battery = psutil.sensors_battery()
        status = BRAIN.status()
        return {
            "cpu": round(cpu, 1),
            "ram": round(mem.percent, 1),
            "ram_used": round(mem.used / 2**30, 1),
            "ram_total": round(mem.total / 2**30, 1),
            "disk": round(disk.percent, 1),
            "battery": round(battery.percent) if battery else None,
            "charging": bool(battery and battery.power_plugged),
            "uptime": int(time.time() - STARTED),
            "online": status["online"],
            "warmed": status.get("warmed", False),
            "provider": status.get("provider", "ollama"),
            "model": status["model"],
            "models": status["models"],
            "tool_count": len(tools.TOOLS),
            "facts": memory.stats()["facts"],
        }
    except Exception as exc:
        return {"error": str(exc)}


def greeting() -> str:
    hour = time.localtime().tm_hour
    part = "Good morning" if hour < 12 else ("Good afternoon" if hour < 18 else "Good evening")
    name = CONFIG["identity"]["user_name"]
    status = BRAIN.status()
    if not status["online"]:
        return f"{part}, {name}. Cognitive core offline; reflex systems standing by."
    return f"{part}, {name}. All systems online. At your service."


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AUDEN/2.0"

    # ---------------- plumbing ---------------- #
    def log_message(self, fmt, *args):  # silence default noisy logging
        return

    def _headers(self, code: int, ctype: str, length: int | None = None,
                 extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if length is not None:
            self.send_header("Content-Length", str(length))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
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
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _authed(self) -> bool:
        return self.headers.get("X-Auden-Token") == TOKEN

    def _guard(self) -> bool:
        origin = self.headers.get("Origin")
        if origin and "127.0.0.1" not in origin and "localhost" not in origin:
            self._json({"error": "forbidden origin"}, 403)
            return False
        if not self._authed():
            self._json({"error": "unauthorized"}, 401)
            return False
        return True

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _sse_send(self, event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
        try:
            self.wfile.write(f"{len(payload):X}\r\n".encode() + payload + b"\r\n")
            self.wfile.flush()
        except Exception as exc:
            raise ClientGone() from exc

    def _sse_end(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except Exception:
            pass

    # ---------------- routes ---------------- #
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            return self._serve_index()
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path.startswith("/ui/"):
            return self._serve_static(path[4:])
        if path.startswith("/api/"):
            if not self._guard():
                return
            if path == "/api/state":
                return self._json({
                    "online": True,
                    "brain": BRAIN.status(),
                    "telemetry": telemetry(),
                    "tools": [{"name": n, "category": t["category"], "confirm": tools.needs_confirm(n)}
                              for n, t in tools.TOOLS.items()],
                    "config": {
                        "accent": CONFIG["ui"]["accent"],
                        "voice": CONFIG["voice"],
                        "wake": CONFIG["wake"],
                        "user": CONFIG["identity"]["user_name"],
                        "assistant": CONFIG["identity"]["assistant_name"],
                        "greet": CONFIG["ui"]["greet_on_start"],
                        "start_mode": CONFIG["ui"].get("start_mode", "full"),
                    },
                })
            if path == "/api/telemetry":
                return self._json(telemetry())
            if path == "/api/facts":
                return self._json({"facts": memory.all_facts(), "stats": memory.stats()})
            if path == "/api/greeting":
                return self._json({"text": greeting()})
            if path == "/api/events":
                return self._event_stream()
            return self._json({"error": "not found"}, 404)
        self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if not path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        if not self._guard():
            return

        if path == "/api/chat":
            return self._chat()
        if path == "/api/confirm":
            body = self._body()
            with CONFIRM_LOCK:
                slot = CONFIRM_EVENTS.get(str(body.get("id")))
            if slot:
                slot["approved"] = bool(body.get("approved"))
                slot["event"].set()
            return self._json({"ok": bool(slot)})
        if path == "/api/facts":
            body = self._body()
            result = memory.remember(str(body.get("fact", "")), str(body.get("category", "general")))
            return self._json({"result": result, "facts": memory.all_facts()})
        if path == "/api/facts/delete":
            body = self._body()
            return self._json({"result": memory.forget(str(body.get("keyword", ""))), "facts": memory.all_facts()})
        if path == "/api/reset":
            BRAIN.reset()
            return self._json({"ok": True})
        if path == "/api/window":
            body = self._body()
            mode = str(body.get("mode") or "full").lower()
            result = win.apply(mode)
            if result.get("ok") and body.get("persist", True):
                save_config({"ui": {"start_mode": mode}})
            return self._json(result)
        if path == "/api/settings":
            body = self._body()
            saved = save_config({k: v for k, v in body.items() if k in {"voice", "wake", "brain", "location", "identity"}})
            BRAIN.__init__()  # reload model/host settings
            return self._json({"ok": True, "config": saved})
        if path == "/api/warmup":
            threading.Thread(target=BRAIN.warmup, daemon=True).start()
            return self._json({"ok": True})
        if path == "/api/shutdown":
            self._json({"ok": True})
            SHUTDOWN.set()
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._json({"error": "not found"}, 404)

    # ---------------- handlers ---------------- #
    def _serve_index(self) -> None:
        file = UI_DIR / "index.html"
        if not file.exists():
            return self._json({"error": "ui/index.html missing"}, 500)
        page = file.read_text(encoding="utf-8")
        page = page.replace("__TOKEN__", TOKEN)
        page = page.replace("__BOOT_DATA__", json.dumps({
            "config": {
                "accent": CONFIG["ui"]["accent"],
                "voice": CONFIG["voice"],
                "wake": CONFIG["wake"],
                "user": CONFIG["identity"]["user_name"],
                "assistant": CONFIG["identity"]["assistant_name"],
                "greet": CONFIG["ui"]["greet_on_start"],
            }
        }))
        raw = page.encode("utf-8")
        self._headers(200, "text/html; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def _serve_static(self, rel: str) -> None:
        target = (UI_DIR / rel.replace("\\", "/")).resolve()
        if UI_DIR.resolve() not in target.parents and target != UI_DIR.resolve():
            return self._json({"error": "forbidden"}, 403)
        if not target.is_file():
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        raw = target.read_bytes()
        self._headers(200, ctype, len(raw))
        self.wfile.write(raw)

    def _event_stream(self) -> None:
        q: queue.Queue = queue.Queue()
        with SUB_LOCK:
            SUBSCRIBERS.append(q)
        try:
            self._sse_start()
            self._sse_send("hello", {"ok": True})
            while not SHUTDOWN.is_set():
                try:
                    event = q.get(timeout=15)
                    self._sse_send(event.get("type", "message"), event)
                except queue.Empty:
                    self._sse_send("ping", {"t": time.time()})
        except ClientGone:
            pass
        finally:
            with SUB_LOCK:
                if q in SUBSCRIBERS:
                    SUBSCRIBERS.remove(q)

    def _chat(self) -> None:
        body = self._body()
        text = str(body.get("text", "")).strip()
        if not text:
            return self._json({"error": "empty message"}, 400)

        self._sse_start()

        def emit(event: str, data: dict) -> None:
            self._sse_send(event, data)

        def ask_confirm(name: str, args: dict) -> bool:
            cid = secrets.token_hex(6)
            slot = {"event": threading.Event(), "approved": False}
            with CONFIRM_LOCK:
                CONFIRM_EVENTS[cid] = slot
            emit("confirm", {"id": cid, "tool": name, "args": args})
            approved = slot["event"].wait(timeout=90) and slot["approved"]
            with CONFIRM_LOCK:
                CONFIRM_EVENTS.pop(cid, None)
            if not slot["event"].is_set():
                emit("notice", {"text": "Confirmation timed out; action cancelled."})
            return bool(approved)

        try:
            reply = BRAIN.respond(text, emit, ask_confirm)
            emit("done", {"text": reply, "telemetry": telemetry()})
        except ClientGone:
            pass
        except Exception as exc:
            try:
                emit("error", {"message": str(exc)[:400]})
            except ClientGone:
                pass
        finally:
            self._sse_end()
            self.close_connection = True


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        """Browsers drop SSE connections abruptly; that is not an error worth printing."""
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def create(port: int = 8765) -> Server:
    httpd = Server(("127.0.0.1", port), Handler)
    return httpd
