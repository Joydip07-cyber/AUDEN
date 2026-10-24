#!/usr/bin/env python3
"""A.U.D.E.N launcher.

Starts the local core, then opens the HUD as a chromeless desktop window
(a Chromium browser in app mode) or falls back to the default browser /
console.

    python auden.py            # HUD window
    python auden.py --console  # terminal chat
    python auden.py --no-window
    python auden.py --setup    # rerun the first-run wizard
"""
from __future__ import annotations

import argparse
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

# Must be set before core.paths is imported.
if "--portable" in sys.argv:
    os.environ["AUDEN_PORTABLE"] = "1"

from core import browser as browsers  # noqa: E402
from core import paths, provision, window as win  # noqa: E402
from core.config import cfg  # noqa: E402
from core.version import __version__  # noqa: E402

BANNER = r"""
 ###  #   # ####  ##### #   #
#   # #   # #   # #     ##  #
##### #   # #   # ####  # # #
#   # #   # #   # #     #  ##
#   #  ###  ####  ##### #   #

  local cognitive system  -  build 2.0
"""

_MUTEX = None


def _redirect_output() -> None:
    """Windowed builds have no console; keep a log file for support."""
    if not paths.is_frozen():
        return
    try:
        paths.logs_dir().mkdir(parents=True, exist_ok=True)
        log = paths.logs_dir() / "auden.log"
        try:
            if log.is_file() and log.stat().st_size > 2_000_000:
                old = paths.logs_dir() / "auden.old.log"
                if old.exists():
                    old.unlink()
                log.replace(old)
        except OSError:
            pass
        stream = open(log, "a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
    except Exception:
        pass


def acquire_instance() -> bool:
    """One AUDEN per user. A second launch focuses the existing window."""
    global _MUTEX
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        _MUTEX = kernel32.CreateMutexW(None, False, "Local\\AUDEN.SingleInstance")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            for title in (win.TITLE, "A.U.D.E.N Setup"):
                hwnd = win.find(title)
                if hwnd:
                    user32 = ctypes.windll.user32
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    user32.SetForegroundWindow(hwnd)
                    break
            return False
    except Exception:
        pass
    return True


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def wait_ready(port: int, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.15)
    return False


def open_window(url: str, width: int, height: int, x: int = 80, y: int = 40,
                profile_name: str = "window-profile") -> bool:
    browser = browsers.chromium_exe()
    if not browser:
        return False
    profile = paths.data_dir() / profile_name
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        str(browser),
        f"--app={url}",
        f"--window-size={width},{height}",
        f"--window-position={x},{y}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--autoplay-policy=no-user-gesture-required",
    ]
    try:
        subprocess.Popen(args, close_fds=True)
        return True
    except Exception as exc:
        print(f"[auden] could not launch app window ({exc})")
        return False


def wait_for_window(title: str, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if win.find(title):
            return True
        time.sleep(0.2)
    return False


def console_loop() -> None:
    from core import brain

    core_brain = brain.Brain()

    def emit(event: str, data: dict) -> None:
        if event == "token":
            print(data.get("text", ""), end="", flush=True)
        elif event == "tool":
            print(f"\n  [tool] {data['name']}({data.get('args')})", flush=True)
        elif event == "tool_result":
            print(f"  [result] {str(data.get('result'))[:400]}", flush=True)

    def confirm(name: str, args: dict) -> bool:
        answer = input(f"\n  Authorise {name} {args}? [y/N] ").strip().lower()
        return answer in {"y", "yes"}

    print("Console mode. Ctrl+C to exit.\n")
    status = core_brain.status()
    print(f"Model: {status['model']} ({'online' if status['online'] else 'OFFLINE'})\n")
    while True:
        try:
            text = input("\nyou > ").strip()
            if not text:
                continue
            if text in {"exit", "quit", "bye"}:
                break
            print("auden > ", end="", flush=True)
            core_brain.respond(text, emit, confirm)
            print()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye, sir.")
            break


def run_setup() -> bool:
    """Show the first-run wizard and wait for it to finish or be closed."""
    from core import setup_server

    httpd, port = setup_server.create()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    x, y, w, h = win.centered(1000, 700)
    # A separate browser profile is important: the setup window is closed just
    # before the HUD opens, and Edge can otherwise hand the new launch to a
    # process that is still shutting down.
    opened = open_window(url, w, h, x, y, profile_name="setup-profile")
    if opened and wait_for_window("A.U.D.E.N Setup", 20.0):
        def place() -> None:
            time.sleep(0.8)
            for _ in range(15):
                if win.set_geometry("A.U.D.E.N Setup", x, y, w, h):
                    break
                time.sleep(0.4)

        threading.Thread(target=place, daemon=True).start()
    else:
        print("[auden] setup window unavailable; using the default browser.")
        webbrowser.open(url)
        opened = False

    appeared = opened
    missing_at = None
    deadline = time.time() + 1800
    try:
        while not setup_server.FINISHED.is_set() and not setup_server.CANCELLED.is_set():
            if time.time() > deadline:
                print("[auden] setup timed out.")
                break
            if opened:
                if win.find("A.U.D.E.N Setup"):
                    appeared = True
                    missing_at = None
                elif appeared:
                    if missing_at is None:
                        missing_at = time.time()
                    elif time.time() - missing_at > 2.0:
                        print("[auden] setup window closed.")
                        break
            time.sleep(0.4)
    finally:
        win.close("A.U.D.E.N Setup")
        try:
            httpd.shutdown()
        except Exception:
            pass
        if not setup_server.FINISHED.is_set():
            provision.cancel()
    return setup_server.FINISHED.is_set()


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch AUDEN")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-window", action="store_true", help="serve only, do not open a window")
    parser.add_argument("--mini", action="store_true", help="start as the small always-on-top window")
    parser.add_argument("--console", action="store_true", help="terminal chat instead of the HUD")
    parser.add_argument("--setup", action="store_true", help="run the first-run setup wizard")
    parser.add_argument("--portable", action="store_true", help="keep data beside the executable")
    parser.add_argument("--version", action="version", version=f"AUDEN {__version__}")
    args = parser.parse_args()

    paths.ensure()
    _redirect_output()
    print(f"[auden] v{__version__}  data={paths.data_dir()}  config={paths.config_path()}")

    if not acquire_instance():
        print("[auden] already running; focused the existing window.")
        return 0

    if args.console:
        provision.ensure_engine()
        console_loop()
        provision.shutdown()
        return 0

    first_run = (
        args.setup
        or not paths.config_path().is_file()
        or (paths.is_frozen() and not cfg("app", "setup_complete", default=False))
    )
    if first_run:
        if not run_setup():
            print("[auden] setup cancelled.")
            provision.shutdown()
            return 0
        print("[auden] setup complete.")
    elif not provision.ensure_engine():
        print("[auden] Ollama is not reachable; starting in offline reflex mode.")

    # Import after setup: server.BRAIN is created from the freshly saved config.
    from core import server

    port = args.port
    while not port_free(port) and port < args.port + 20:
        port += 1

    print(BANNER)
    httpd = server.create(port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    threading.Thread(target=server.BRAIN.warmup, daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    if not wait_ready(port):
        print("[auden] server failed to start.")
        provision.shutdown()
        return 1

    status = server.BRAIN.status()
    print(f"  core      {'ONLINE' if status['online'] else 'OFFLINE'}  ({status['model']})")
    if not status["online"]:
        print("  !  Ollama is not running or the model is missing.")
        print("     Run  AUDEN.exe --setup  to install the engine.")
    print(f"  tools     {len(server.tools.TOOLS)} registered")
    print(f"  hud       {url}")
    print("  stop      Ctrl+C\n")

    window_opened = False
    window_seen = False
    if not args.no_window:
        mode = "mini" if args.mini else str(server.CONFIG["ui"].get("start_mode", "full")).lower()
        if mode not in win.MODES:
            mode = "full"
        # A HUD left over from a crashed run may point at a dead server.
        if win.find():
            win.close()

        wx, wy, ww, wh = win.placement(mode)
        launched = open_window(f"{url}?mode={mode}", ww, wh, wx, wy)
        if launched and wait_for_window(win.TITLE, 15.0):
            window_opened = True
            window_seen = True

            def _place() -> None:
                time.sleep(1.0)
                for _ in range(16):
                    result = win.apply(mode)
                    if result.get("ok"):
                        time.sleep(0.7)
                        if not win.is_iconic():
                            break
                    time.sleep(0.6)
                time.sleep(1.0)
                win.apply(mode)

            threading.Thread(target=_place, daemon=True).start()
        else:
            print("[auden] app window did not appear; falling back to the default browser.")
            webbrowser.open(url)

    last_active = time.time()
    window_gone = None
    idle_timeout = float(cfg("app", "idle_timeout", default=1800))
    try:
        while not server.SHUTDOWN.is_set():
            time.sleep(0.5)
            if server.SUBSCRIBERS:
                last_active = time.time()
            elif time.time() - last_active > idle_timeout:
                print(f"[auden] idle for {int(idle_timeout)} seconds, shutting down.")
                break

            if window_opened:
                if win.find():
                    window_seen = True
                    window_gone = None
                elif window_seen:
                    if window_gone is None:
                        window_gone = time.time()
                    elif time.time() - window_gone > 2.5:
                        print("[auden] HUD closed, shutting down.")
                        break
    except KeyboardInterrupt:
        print("\n[auden] shutting down.")
    finally:
        server.SHUTDOWN.set()
        try:
            httpd.shutdown()
        except Exception:
            pass
        if window_opened:
            win.close()
        provision.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
