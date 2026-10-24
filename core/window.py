"""Window geometry for the Edge app shell.

The HUD is a web page, and a page cannot resize or pin its own top-level
window. So the Python side does it with Win32 calls, and the page simply
switches its layout to match.

    full   1280x830 (clamped to the screen), centred, normal z-order
    mini    420x640, bottom-right, always on top   (Cortana-sized)
    orb     320x240, bottom-right, always on top   (just the reactor)

Used by auden.py at launch and by POST /api/window at runtime.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

TITLE = "A.U.D.E.N"

MODES: dict[str, tuple[int, int, bool]] = {
    "full": (1280, 830, False),
    "mini": (420, 640, True),
    # Chromium enforces a ~320x240 minimum for app windows, so an honest
    # 200x200 orb is impossible; keep the reactor inside that frame instead.
    "orb": (320, 240, True),
}

MARGIN = 16
SW_RESTORE = 9
SWP_SHOWWINDOW = 0x0040
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SPI_GETWORKAREA = 0x0030
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

_LOCK = threading.Lock()
_DESIRED = {"hwnd": 0, "topmost": False}
_WATCHER: threading.Thread | None = None


def _dpi_aware() -> None:
    """Without this, coordinates are virtualised on scaled displays."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_dpi_aware()


def _work_area() -> tuple[int, int, int, int]:
    """Screen area excluding the taskbar."""
    rect = wintypes.RECT()
    try:
        ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    except Exception:
        return 0, 0, 1920, 1080
    return rect.left, rect.top, rect.right, rect.bottom


def _taskbar_top() -> int:
    """Top edge of the taskbar, or 0 if it cannot be read.

    An auto-hidden taskbar leaves SPI_GETWORKAREA at the full screen size, but
    compact windows should still sit above the bar's rectangle so the dock is
    not covered when the bar slides up.
    """
    try:
        class APPBARDATA(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uCallbackMessage", wintypes.UINT),
                ("uEdge", wintypes.UINT),
                ("rc", wintypes.RECT),
                ("lParam", wintypes.LPARAM),
            ]

        data = APPBARDATA()
        data.cbSize = ctypes.sizeof(APPBARDATA)
        if ctypes.windll.shell32.SHAppBarMessage(5, ctypes.byref(data)):  # ABM_GETTASKBARPOS
            if data.uEdge == 3 and data.rc.top > 0:  # ABE_BOTTOM
                return data.rc.top
    except Exception:
        pass
    return 0


def placement(mode: str) -> tuple[int, int, int, int]:
    """(x, y, width, height) for a mode, without touching the window."""
    mode = (mode or "full").lower()
    if mode not in MODES:
        mode = "full"
    w, h, _ = MODES[mode]
    left, top, right, bottom = _work_area()
    # Never open taller/wider than the usable desktop: 830px is fine on paper
    # but this machine is 1366x768, so clamp and re-centre.
    w = max(320, min(w, (right - left) - 2 * MARGIN))
    h = max(240, min(h, (bottom - top) - 2 * MARGIN))
    if mode == "full":
        x = left + max(0, (right - left - w) // 2)
        y = top + max(0, (bottom - top - h) // 2)
    else:
        floor = _taskbar_top() or bottom
        x = max(left, right - w - MARGIN)
        y = max(top, floor - h - MARGIN)
    return x, y, w, h


def centered(width: int, height: int) -> tuple[int, int, int, int]:
    """A centred rectangle for dialogs such as the first-run setup window."""
    left, top, right, bottom = _work_area()
    width = max(480, min(width, (right - left) - 2 * MARGIN))
    height = max(360, min(height, (bottom - top) - 2 * MARGIN))
    return (
        left + max(0, (right - left - width) // 2),
        top + max(0, (bottom - top - height) // 2),
        width,
        height,
    )


def set_geometry(title: str, x: int, y: int, w: int, h: int) -> bool:
    """Resize/move a window without changing its topmost state."""
    hwnd = find(title)
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPos(hwnd, wintypes.HWND(HWND_NOTOPMOST), x, y, w, h, SWP_SHOWWINDOW)
        return True
    except Exception:
        return False


def find(title: str = TITLE) -> int:
    """Find the real app window, ignoring hidden helper windows with the title."""
    user32 = ctypes.windll.user32
    target = (title or "").strip().lower()
    matches: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _scan(candidate, _lparam):
        if not user32.IsWindowVisible(candidate):
            return True
        length = user32.GetWindowTextLengthW(candidate)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(candidate, buf, length + 1)
        if buf.value.strip().lower() != target:
            return True
        if user32.GetWindow(candidate, 4):  # GW_OWNER: skip tool/owned windows
            return True
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(candidate, cls, 64)
        if not cls.value.startswith("Chrome_WidgetWin"):
            return True
        if user32.IsIconic(candidate):
            # Minimised windows report -32000,-32000 and are only a fallback.
            matches.append((0, candidate))
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(candidate, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w < 160 or h < 120:
            return True
        matches.append((w * h, candidate))
        return True

    user32.EnumWindows(_scan, 0)
    if matches:
        matches.sort(reverse=True)
        return matches[0][1]
    # Do not use FindWindowW(None, title) as a fallback here. Windows 10/11
    # leaves a visible explorer.exe "TabProxyWindow" with the same title after
    # a Chromium app window closes; returning it makes the launcher believe the
    # HUD is still open forever.
    return 0


def apply(mode: str, title: str = TITLE, retries: int = 1) -> dict:
    """Resize, move and pin/unpin the window. Retries while it starts up."""
    mode = (mode or "full").lower()
    if mode not in MODES:
        return {"ok": False, "error": f"unknown mode '{mode}'"}

    hwnd = 0
    for _ in range(max(1, retries)):
        hwnd = find(title)
        if hwnd:
            break
        time.sleep(0.25)
    if not hwnd:
        return {"ok": False, "error": "window not found"}

    user32 = ctypes.windll.user32
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
    except Exception:
        pass

    x, y, w, h = placement(mode)
    topmost = MODES[mode][2]
    insert_after = wintypes.HWND(HWND_TOPMOST if topmost else HWND_NOTOPMOST)
    try:
        for _ in range(4):
            user32.SetWindowPos(hwnd, insert_after, x, y, w, h, SWP_SHOWWINDOW)
            time.sleep(0.15)
            # Edge re-asserts its own z-order once while starting up, so verify
            # and re-apply instead of assuming the first call stuck.
            if not topmost or _is_topmost(hwnd):
                break
    except Exception as exc:
        return {"ok": False, "error": f"SetWindowPos failed: {exc}"}

    with _LOCK:
        _DESIRED["hwnd"] = hwnd if topmost else 0
        _DESIRED["topmost"] = topmost
    if topmost:
        _ensure_watcher()

    return {"ok": True, "mode": mode, "rect": [x, y, w, h], "topmost": topmost}


def _ensure_watcher() -> None:
    global _WATCHER
    if _WATCHER is None or not _WATCHER.is_alive():
        _WATCHER = threading.Thread(target=_watch_topmost, daemon=True)
        _WATCHER.start()


def _watch_topmost() -> None:
    """Chromium clears WS_EX_TOPMOST after its own resizes. Keep it pinned.

    Only runs while a compact mode asked to be on top; switching back to full
    clears the desire and the loop goes idle.
    """
    user32 = ctypes.windll.user32
    while True:
        time.sleep(1.0)
        with _LOCK:
            hwnd = _DESIRED["hwnd"]
            wanted = _DESIRED["topmost"]
        if not wanted:
            continue
        if not hwnd or not user32.IsWindow(hwnd):
            # The window we pinned was closed and replaced (relaunch): bind to
            # whatever HUD window exists now instead of idling on a dead handle.
            hwnd = find()
            if not hwnd:
                continue
            with _LOCK:
                _DESIRED["hwnd"] = hwnd
        try:
            if _is_topmost(hwnd):
                continue
            user32.SetWindowPos(
                hwnd, wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass


def _is_topmost(hwnd: int) -> bool:
    ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
    return bool(ex_style & 0x8)  # WS_EX_TOPMOST


def close(title: str = TITLE, wait: float = 1.5) -> bool:
    """Ask the HUD window to close (used to avoid stacking windows)."""
    hwnd = find(title)
    if not hwnd:
        return False
    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
    deadline = time.time() + wait
    while time.time() < deadline:
        if not ctypes.windll.user32.IsWindow(hwnd):
            break
        time.sleep(0.1)
    return True


def is_iconic(title: str = TITLE) -> bool:
    hwnd = find(title)
    return bool(hwnd and ctypes.windll.user32.IsIconic(hwnd))


def info(title: str = TITLE) -> dict:
    """Current window rectangle, mostly for diagnostics/tests."""
    hwnd = find(title)
    if not hwnd:
        return {"ok": False, "error": "window not found"}
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return {
        "ok": True,
        "hwnd": hwnd,
        "rect": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top],
    }
