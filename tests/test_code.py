"""Code-mode checks: fenced blocks survive cleaning, intent detection is sane,
and relative paths land in the workspace or the real user folders."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import brain, tools  # noqa: E402

ok = 0
bad = 0


def check(label: str, cond: bool) -> None:
    global ok, bad
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        bad += 1
        print(f"  FAIL  {label}")


source = "def reverse(s):\n    return s[::-1]\n"
reply = "Certainly, sir.\n```python\n" + source + "```\nUse it well."
cleaned = brain.Brain._clean(reply)

check("fence preserved", "```python" in cleaned and cleaned.count("```") == 2)
check("body intact", source in cleaned)
check("prose intact", "Certainly, sir." in cleaned and "Use it well." in cleaned)
check("newlines kept", "\n" in cleaned and "def reverse(s):\n    return" in cleaned)

check("plain prose still tidy", brain.Brain._clean("**Hello**, sir.") == "Hello, sir.")
check("code intent: python function", brain.wants_code("write a python function that reverses a string"))
check("code intent: fix bug", brain.wants_code("can you fix this bug in my script?"))
check("code intent: explain", brain.wants_code("explain this regex"))
check("no code intent: open folder", not brain.wants_code("open the code folder"))
check("no code intent: weather", not brain.wants_code("what is the weather like"))

home = Path.home()
check("workspace relative", tools._resolve("notes.txt") == (ROOT / "notes.txt").resolve())
check("Desktop alias", tools._resolve(r"Desktop\demo.py") == (home / "Desktop" / "demo.py").resolve())
check("Documents alias", tools._resolve("Documents/a.md") == (home / "Documents" / "a.md").resolve())
check("tilde expands", tools._resolve("~/Desktop/x.txt") == (home / "Desktop" / "x.txt").resolve())
check("absolute untouched", tools._resolve(r"C:\Windows\win.ini") == Path(r"C:\Windows\win.ini"))

print(f"\n  {ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
