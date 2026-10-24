"""Tool belt for AUDEN.

Every capability is a plain function registered with @tool(), which automatically
builds the JSON schema handed to the local model. Handlers return human-readable
strings: they are fed back to the model *and* shown in the HUD.
"""
from __future__ import annotations

import ast
import copy
import ctypes
import datetime as _dt
import html
import json
import math
import os
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import psutil

from . import browser as browsers
from . import memory, paths
from .config import DATA_DIR, cfg

TOOLS: dict[str, dict] = {}
_NOTIFIER = None
CREATE_NO_WINDOW = 0x08000000
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def set_notifier(fn) -> None:
    """Server registers a broadcast function for async events such as timers."""
    global _NOTIFIER
    _NOTIFIER = fn


def tool(name: str, description: str, params: dict | None = None,
         required: list[str] | None = None, confirm: bool = False, category: str = "system",
         core: bool = False):
    def decorator(fn):
        TOOLS[name] = {
            "fn": fn,
            "confirm": confirm,
            "category": category,
            "core": core,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": params or {},
                        "required": required or [],
                    },
                },
            },
            "help": f"{name}({', '.join(required or [])}) - {description}",
        }
        return fn

    return decorator


def specs(compact: bool = True, core_only: bool | None = None) -> list[dict]:
    """Tool schemas for the model.

    Every schema token is prompt tokens the CPU has to chew through, so the
    default output is trimmed: short one-line descriptions, no per-parameter
    prose. Set `brain.core_tools_only` to shrink further to the essentials.
    """
    if core_only is None:
        core_only = bool(cfg("brain", "core_tools_only", default=False))
    out = []
    for entry in TOOLS.values():
        if core_only and not entry.get("core"):
            continue
        schema = copy.deepcopy(entry["schema"])
        if compact:
            fn = schema["function"]
            fn["description"] = fn["description"].split(".")[0][:72]
            for prop in (fn["parameters"].get("properties") or {}).values():
                prop.pop("description", None)
                prop.pop("enum", None)
        out.append(schema)
    return out


def help_text() -> str:
    return "\n".join(f"- {t['help']}" for t in TOOLS.values())


def names() -> str:
    return ", ".join(TOOLS)


def needs_confirm(name: str) -> bool:
    entry = TOOLS.get(name)
    return bool(entry and (entry["confirm"] or name in (cfg("safety", "confirm_tools", default=[]) or [])))


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _s(value, default="", limit=600) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    return text[:limit]


def _int(value, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return default


def _ps(command: str, timeout: int = 30) -> str:
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace",
        )
        out = (done.stdout or "").strip()
        err = (done.stderr or "").strip()
        return out if out else (err or "(no output)")
    except subprocess.TimeoutExpired:
        return f"(timed out after {timeout}s)"
    except Exception as exc:
        return f"(error: {exc})"


def _http(url: str, data: bytes | None = None, timeout: int = 15) -> str:
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA,
        "Accept-Language": "en-GB,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def _strip_html(raw: str, limit: int = 5000) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    return text[:limit]


ROOT = Path(os.path.expandvars(cfg("safety", "workspace", default="") or paths.workspace_dir())).resolve()
_HOME_ALIASES = {"desktop": "Desktop", "documents": "Documents", "downloads": "Downloads"}


def _resolve(path: str) -> Path:
    """Expand ~ and env vars, then anchor relative paths at the workspace.

    Models often answer with 'Desktop/notes.txt' meaning the real Desktop, or
    just 'script.py' meaning the project folder. Honour both instead of relying
    on the process working directory.
    """
    raw = os.path.expandvars(os.path.expanduser(_s(path, limit=1000))).strip().strip('"')
    if not raw:
        return ROOT
    p = Path(raw)
    if not p.is_absolute():
        first, _, rest = raw.replace("\\", "/").partition("/")
        alias = _HOME_ALIASES.get(first.lower())
        p = (Path.home() / alias / rest) if alias else (ROOT / p)
    return p.resolve()


def _writable(path: Path) -> bool:
    roots = cfg("safety", "write_roots", default=[]) or []
    try:
        for root in roots:
            r = Path(os.path.expandvars(root)).resolve()
            if path == r or r in path.parents:
                return True
    except Exception:
        pass
    return False


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# --------------------------------------------------------------------------- #
# time / info
# --------------------------------------------------------------------------- #

@tool("get_time", "Current local date and time. Use for 'what time is it' or 'what's the date'.",
      category="info")
def get_time() -> str:
    now = _dt.datetime.now().astimezone()
    return now.strftime("It is %H:%M on %A, %d %B %Y (%Z).")


@tool("system_status", "Live PC health: CPU load, RAM, disk space, battery, uptime.", category="system")
def system_status() -> str:
    cpu = psutil.cpu_percent(interval=0.35)
    freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path.home().anchor or "C:\\"))
    boot = _dt.datetime.fromtimestamp(psutil.boot_time())
    up = _dt.datetime.now() - boot
    hours, rem = divmod(int(up.total_seconds()), 3600)
    parts = [
        f"CPU {cpu:.0f}%" + (f" at {freq.current/1000:.1f} GHz" if freq else ""),
        f"RAM {_fmt_bytes(mem.used)} of {_fmt_bytes(mem.total)} ({mem.percent:.0f}%)",
        f"Disk {_fmt_bytes(disk.free)} free of {_fmt_bytes(disk.total)}",
        f"Uptime {hours}h {rem // 60}m",
    ]
    battery = psutil.sensors_battery()
    if battery:
        state = "charging" if battery.power_plugged else "on battery"
        parts.append(f"Battery {battery.percent:.0f}% ({state})")
    return "Systems nominal. " + ", ".join(parts) + "."


@tool("get_weather", "Current weather and today's forecast for a city.",
      params={"city": {"type": "string", "description": "City name. Leave empty for the current location."}},
      category="info")
def get_weather(city: str = "") -> str:
    city = _s(city) or _s(cfg("location", "city", default=""))
    imperial = "f" if str(cfg("location", "units", default="metric")).lower().startswith("imp") else "m"
    url = f"https://wttr.in/{urllib.parse.quote(city) if city else ''}?format=j1&m" if imperial == "m" else \
          f"https://wttr.in/{urllib.parse.quote(city) if city else ''}?format=j1"
    try:
        data = json.loads(_http(url, timeout=15))
    except Exception as exc:
        return f"Weather service unavailable ({exc})."
    cur = (data.get("current_condition") or [{}])[0]
    area = (data.get("nearest_area") or [{}])[0]
    place = ", ".join(filter(None, [
        ((area.get("areaName") or [{}])[0] or {}).get("value", ""),
        ((area.get("country") or [{}])[0] or {}).get("value", ""),
    ])) or city or "your location"
    unit = "C" if imperial == "m" else "F"
    desc = ((cur.get("weatherDesc") or [{}])[0] or {}).get("value", "unknown conditions")
    today = (data.get("weather") or [{}])[0]
    line = (
        f"{desc} in {place}: {cur.get(f'temp_{unit}')}°{unit} "
        f"(feels like {cur.get(f'FeelsLike{unit}')}°{unit}), humidity {cur.get('humidity')}%, "
        f"wind {cur.get('windspeedKmph')} km/h."
    )
    if today:
        line += f" Today {today.get(f'mintemp{unit}')}–{today.get(f'maxtemp{unit}')}°{unit}, sunrise {today.get('sunrise')}, sunset {today.get('sunset')}."
    return line


@tool("calculate", "Evaluate a maths expression precisely.",
      params={"expression": {"type": "string", "description": "e.g. (1850*12)/7 or sqrt(144)+2**10"}},
      required=["expression"], category="info")
def calculate(expression: str) -> str:
    expr = _s(expression, limit=300)
    allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    allowed.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})
    try:
        tree = ast.parse(expr, mode="eval")

        def ev(node):
            if isinstance(node, ast.Expression):
                return ev(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp):
                ops = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                       ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
                       ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
                       ast.Pow: lambda a, b: a ** b}
                fn = ops.get(type(node.op))
                if not fn:
                    raise ValueError("unsupported operator")
                return fn(ev(node.left), ev(node.right))
            if isinstance(node, ast.UnaryOp):
                val = ev(node.operand)
                return -val if isinstance(node.op, ast.USub) else val
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in allowed:
                return allowed[node.func.id](*[ev(a) for a in node.args])
            if isinstance(node, ast.Name) and node.id in {"pi", "e", "tau"}:
                return getattr(math, node.id)
            raise ValueError("unsupported expression")

        result = ev(tree)
        pretty = f"{result:,.6g}" if isinstance(result, float) else f"{result:,}"
        return f"{expr} = {pretty}"
    except Exception as exc:
        return f"I could not evaluate that ({exc})."


# --------------------------------------------------------------------------- #
# apps / system control
# --------------------------------------------------------------------------- #

APP_MAP = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe",
    "paint": "mspaint.exe", "explorer": "explorer.exe", "files": "explorer.exe",
    "file explorer": "explorer.exe", "cmd": "cmd.exe", "command prompt": "cmd.exe",
    "terminal": "wt.exe", "windows terminal": "wt.exe", "powershell": "powershell.exe",
    "spotify": "spotify:",
    "vscode": "code", "vs code": "code", "visual studio code": "code",
    "word": "winword.exe", "excel": "excel.exe", "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe", "settings": "ms-settings:", "store": "ms-windows-store:",
    "camera": "microsoft.windows.camera:", "task manager": "taskmgr.exe",
    "taskmgr": "taskmgr.exe", "control panel": "control.exe", "snipping tool": "ms-screenclip:",
    "recycle bin": "shell:RecycleBinFolder", "downloads": "shell:Downloads",
    "documents": "shell:Personal", "pictures": "shell:My Pictures",
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com",
    "github": "https://github.com", "chatgpt": "https://chat.openai.com",
    "netflix": "https://www.netflix.com", "maps": "https://maps.google.com",
    "calendar": "https://calendar.google.com", "whatsapp": "https://web.whatsapp.com",
}


@tool("open_app", "Launch an application, folder, website or Windows setting on this PC.",
      params={"name": {"type": "string", "description": "App or site name, e.g. 'spotify', 'chrome', 'youtube', 'calculator'."}},
      required=["name"], category="system")
def open_app(name: str) -> str:
    raw = _s(name, limit=200)
    key = raw.lower().strip().strip("'\"")
    if not key:
        return "No application specified."

    if key in {"browser", "web browser", "default browser", "internet"}:
        launched = browsers.launch()
        return f"Opening {launched}." if launched else "No web browser was detected."
    if key in {"brave", "brave browser", "chrome", "google chrome", "edge",
               "microsoft edge", "firefox", "mozilla firefox", "opera", "vivaldi"}:
        launched = browsers.launch(key)
        if launched:
            return f"Opening {launched}."
        default = browsers.detect()
        label = raw[:1].upper() + raw[1:] if raw else key
        return (f"{label} is not installed. Your default browser is {default['name']}."
                if default else f"{label} is not installed and no browser was detected.")

    target = APP_MAP.get(key, raw)
    try:
        if target.startswith(("http://", "https://")):
            used = browsers.open_url(target)
            return f"Opened {target} in {used}."
        if re.fullmatch(r"[\w.-]+\.[a-z]{2,}(/.*)?", key) and " " not in key:
            url = f"https://{key}"
            used = browsers.open_url(url)
            return f"Opened {url} in {used}."
        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False,
                         creationflags=CREATE_NO_WINDOW, close_fds=True)
        return f"Opened {raw}."
    except Exception as exc:
        return f"Could not open {raw} ({exc})."


@tool("open_url", "Open a specific web address in the default browser.",
      params={"url": {"type": "string", "description": "Full URL including https://"}},
      required=["url"], category="system")
def open_url(url: str) -> str:
    url = _s(url, limit=1000)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    try:
        used = browsers.open_url(url)
        return f"Opened {url} in {used}."
    except Exception as exc:
        return f"Could not open that URL ({exc})."


VK = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1, "mute": 0xAD,
      "volume_up": 0xAF, "volume_down": 0xAE, "stop": 0xB2}


def _tap(vk: int, times: int = 1) -> None:
    user32 = ctypes.windll.user32
    for _ in range(max(1, times)):
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)
        time.sleep(0.03)


@tool("media_control", "Control media playback and system volume.",
      params={"action": {"type": "string", "enum": ["play_pause", "next", "prev", "mute", "volume_up", "volume_down", "stop"],
                         "description": "Which media/volume action to perform"}},
      required=["action"], category="system")
def media_control(action: str) -> str:
    act = _s(action).lower().replace(" ", "_")
    if act in {"pause", "play", "toggle"}:
        act = "play_pause"
    if act in {"louder", "volumeup", "up"}:
        act = "volume_up"
    if act in {"quieter", "volumedown", "down"}:
        act = "volume_down"
    if act not in VK:
        return f"Unknown media action '{action}'."
    times = 5 if act.startswith("volume") else 1
    _tap(VK[act], times)
    return f"Media command '{act}' executed." if not act.startswith("volume") else f"Volume {act.split('_')[1]} adjusted."


@tool("screenshot", "Capture the screen and save it as an image file.", category="system")
def screenshot() -> str:
    out = DATA_DIR / "screenshots" / time.strftime("shot_%Y%m%d_%H%M%S.png")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
        "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size);"
        f"$bmp.Save('{out}');"
        "'saved'"
    )
    result = _ps(script, timeout=25)
    return f"Screenshot saved to {out}." if "saved" in result else f"Screenshot failed: {result}"


@tool("lock_pc", "Lock the workstation immediately.", confirm=True, category="system")
def lock_pc() -> str:
    _ps("rundll32.exe user32.dll,LockWorkStation")
    return "Workstation locked."


@tool("clipboard", "Read or write the Windows clipboard.",
      params={"action": {"type": "string", "enum": ["read", "write"]},
              "text": {"type": "string", "description": "Text to place on the clipboard when action=write"}},
      required=["action"], category="system")
def clipboard(action: str, text: str = "") -> str:
    if _s(action).lower() == "read":
        content = _ps("Get-Clipboard -Raw", timeout=10)
        return f"Clipboard: {content[:800]}" if content else "Clipboard is empty."
    safe = _s(text, limit=2000).replace("'", "''")
    _ps(f"Set-Clipboard -Value '{safe}'", timeout=10)
    return "Copied to clipboard."


@tool("type_text", "Type text into the currently focused window using the keyboard.",
      params={"text": {"type": "string", "description": "Text to type"}},
      required=["text"], confirm=True, category="system")
def type_text(text: str) -> str:
    safe = _s(text, limit=1500).replace("'", "''")
    _ps(f"Set-Clipboard -Value '{safe}'; Start-Sleep -Milliseconds 120;"
        "$w=New-Object -ComObject WScript.Shell; $w.SendKeys('^v')", timeout=15)
    return "Text typed into the active window."


# --------------------------------------------------------------------------- #
# files
# --------------------------------------------------------------------------- #

@tool("list_folder", "List the contents of a folder.",
      params={"path": {"type": "string", "description": "Folder path, e.g. C:/Users/Joy/Downloads"}},
      required=["path"], category="files")
def list_folder(path: str, limit: int = 80) -> str:
    try:
        folder = _resolve(path)
        if not folder.is_dir():
            return f"{folder} is not a folder."
        entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[: _int(limit, 80)]
        lines = []
        for entry in entries:
            try:
                size = _fmt_bytes(entry.stat().st_size) if entry.is_file() else "<dir>"
            except Exception:
                size = "?"
            lines.append(f"{entry.name}  [{size}]")
        return f"{folder} ({len(lines)} shown):\n" + "\n".join(lines)
    except Exception as exc:
        return f"Could not list folder ({exc})."


@tool("search_files", "Search for files by name inside a folder tree.",
      params={"query": {"type": "string", "description": "Part of the file name"},
              "folder": {"type": "string", "description": "Where to search. Defaults to the user's home folder."},
              "limit": {"type": "integer", "description": "Max results, default 25"}},
      required=["query"], category="files")
def search_files(query: str, folder: str = "", limit: int = 25) -> str:
    q = _s(query).lower()
    if not q:
        return "No search term given."
    root = _resolve(folder) if _s(folder) else Path.home()
    skip = {"node_modules", ".git", "__pycache__", "AppData", "Windows", "ProgramData",
            ".venv", "venv", "site-packages", "$Recycle.Bin"}
    hits: list[Path] = []
    deadline = time.time() + 20
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            if time.time() > deadline or len(hits) >= _int(limit, 25):
                break
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            for name in filenames:
                if q in name.lower():
                    hits.append(Path(dirpath) / name)
                    if len(hits) >= _int(limit, 25):
                        break
    except Exception as exc:
        return f"Search failed ({exc})."
    if not hits:
        return f"No files matching '{query}' under {root}."
    lines = []
    for hit in hits:
        try:
            lines.append(f"{hit}  [{_fmt_bytes(hit.stat().st_size)}]")
        except Exception:
            lines.append(str(hit))
    return f"Found {len(hits)} match(es) under {root}:\n" + "\n".join(lines)


@tool("read_file", "Read text from a file.",
      params={"path": {"type": "string", "description": "File path"},
              "start_line": {"type": "integer", "description": "First line, default 1"},
              "max_lines": {"type": "integer", "description": "How many lines, default 120"}},
      required=["path"], category="files")
def read_file(path: str, start_line: int = 1, max_lines: int = 120) -> str:
    try:
        file = _resolve(path)
        if not file.exists():
            return f"No such file: {file}"
        if file.stat().st_size > 2_000_000:
            return f"{file.name} is too large to read ({_fmt_bytes(file.stat().st_size)})."
        text = file.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(1, _int(start_line, 1))
        count = max(1, min(_int(max_lines, 120), 400))
        chunk = lines[start - 1: start - 1 + count]
        body = "\n".join(f"{i + start:>4}| {line}" for i, line in enumerate(chunk))
        more = "" if start - 1 + count >= len(lines) else f"\n... ({len(lines)} lines total)"
        return f"{file}:\n{body}{more}"
    except Exception as exc:
        return f"Could not read file ({exc})."


@tool("write_file", "Create or overwrite a text file in the workspace or an approved folder.",
      params={"path": {"type": "string", "description": "Relative path like 'app.py', or an absolute path in an approved folder"},
              "content": {"type": "string", "description": "Full file contents"}},
      required=["path", "content"], confirm=True, category="files")
def write_file(path: str, content: str) -> str:
    try:
        file = _resolve(path)
        if not _writable(file):
            return f"Write blocked: {file} is outside the approved folders."
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(_s(content, limit=200_000), encoding="utf-8")
        return f"Wrote {len(content)} characters to {file}."
    except Exception as exc:
        return f"Could not write file ({exc})."


@tool("run_command", "Run a PowerShell command on this PC and return its output.",
      params={"command": {"type": "string", "description": "PowerShell command line"},
              "timeout": {"type": "integer", "description": "Seconds before aborting, default 25"}},
      required=["command"], confirm=True, category="system")
def run_command(command: str, timeout: int = 25) -> str:
    if not cfg("safety", "allow_shell", default=True):
        return "Shell access is disabled in config."
    out = _ps(_s(command, limit=2000), timeout=max(5, min(_int(timeout, 25), 120)))
    return out[:4000]


# --------------------------------------------------------------------------- #
# web
# --------------------------------------------------------------------------- #

@tool("web_search", "Search the web and get titles, URLs and snippets.",
      params={"query": {"type": "string", "description": "Search query"}},
      required=["query"], category="web")
def web_search(query: str) -> str:
    q = _s(query, limit=300)
    if not q:
        return "No query given."
    try:
        raw = _http("https://html.duckduckgo.com/html/",
                    data=urllib.parse.urlencode({"q": q}).encode(), timeout=18)
    except Exception as exc:
        return f"Web search failed ({exc})."
    results = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', raw, re.S)
    for idx, (href, title) in enumerate(pattern.findall(raw)[:6]):
        url = html.unescape(href)
        if "uddg=" in url:
            try:
                url = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["uddg"][0])
            except Exception:
                pass
        snippet = _strip_html(snippets[idx], 260) if idx < len(snippets) else ""
        results.append(f"{idx + 1}. {_strip_html(title, 120)}\n   {url}\n   {snippet}")
    if not results:
        return f"No results for '{q}'."
    return f"Top results for '{q}':\n" + "\n".join(results)


@tool("fetch_url", "Download a web page and return its readable text.",
      params={"url": {"type": "string", "description": "Full URL"}},
      required=["url"], category="web")
def fetch_url(url: str) -> str:
    url = _s(url, limit=1000)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        page = _http(url, timeout=20)
    except Exception as exc:
        return f"Could not fetch that page ({exc})."
    return f"Content of {url}:\n{_strip_html(page, 4500)}"


# --------------------------------------------------------------------------- #
# memory / timers
# --------------------------------------------------------------------------- #

@tool("remember", "Store a durable fact about the user for future conversations.",
      params={"fact": {"type": "string", "description": "The fact, written in third person, e.g. 'The user prefers tea over coffee.'"},
              "category": {"type": "string", "description": "Optional category: preference, person, project, schedule, general"}},
      required=["fact"], category="memory")
def remember(fact: str, category: str = "general") -> str:
    return memory.remember(_s(fact, limit=500), _s(category) or "general")


@tool("recall", "Search long-term memory for facts about the user.",
      params={"query": {"type": "string", "description": "What to look for"}},
      required=["query"], category="memory")
def recall(query: str) -> str:
    facts = memory.search_facts(_s(query, limit=200))
    if not facts:
        return "I have nothing on record about that."
    return "From memory:\n" + "\n".join(f"- {f}" for f in facts)


@tool("forget", "Delete memories matching a keyword.",
      params={"keyword": {"type": "string", "description": "Keyword identifying memories to delete"}},
      required=["keyword"], category="memory")
def forget(keyword: str) -> str:
    return memory.forget(_s(keyword, limit=200))


@tool("set_timer", "Set a countdown timer that alerts the user when it ends.",
      params={"seconds": {"type": "integer", "description": "Duration in seconds"},
              "label": {"type": "string", "description": "What the timer is for"}},
      required=["seconds"], category="system")
def set_timer(seconds: int, label: str = "") -> str:
    total = max(1, _int(seconds, 60))
    label = _s(label) or "timer"

    def fire():
        if _NOTIFIER:
            _NOTIFIER({"type": "alarm", "label": label, "seconds": total})

    timer = threading.Timer(total, fire)
    timer.daemon = True
    timer.start()
    mins, secs = divmod(total, 60)
    human = f"{mins} minute(s) {secs} second(s)" if mins else f"{secs} seconds"
    return f"Timer set for {human} ({label})."


# Tools always offered to the model when brain.core_tools_only is enabled.
CORE_TOOLS = {
    "get_time", "system_status", "get_weather", "open_app", "media_control",
    "screenshot", "search_files", "read_file", "write_file", "run_command",
    "web_search", "remember", "recall", "set_timer",
}
for _name in CORE_TOOLS:
    if _name in TOOLS:
        TOOLS[_name]["core"] = True


def run(name: str, args: dict | None = None) -> str:
    entry = TOOLS.get(name)
    if not entry:
        known = ", ".join(sorted(TOOLS))
        return f"Unknown tool '{name}'. Available: {known}"
    args = args or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {}
    if not isinstance(args, dict):
        args = {}
    try:
        result = entry["fn"](**args)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    except TypeError as exc:
        return f"Bad arguments for {name}: {exc}"
    except Exception as exc:
        return f"{name} failed: {exc}"
