"""Agent-loop test against a mock Ollama server (no model required).

    python tests/test_agent.py
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REQUESTS: list[dict] = []


class MockOllama(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        return

    def _json(self, obj):
        raw = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": [{"name": "mock:1"}]})
        else:
            self._json({})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/api/generate":
            return self._json({"response": ""})
        if self.path != "/api/chat":
            return self._json({})
        REQUESTS.append(body)
        saw_tool_result = any(m.get("role") == "tool" for m in body.get("messages", []))

        if not saw_tool_result:
            frames = [
                {"message": {"role": "assistant", "content": "One moment.",
                             "tool_calls": [{"function": {"name": "get_time", "arguments": {}}}]},
                 "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True},
            ]
        else:
            frames = [
                {"message": {"role": "assistant", "content": "It is "}, "done": False},
                {"message": {"role": "assistant", "content": "mock noon."}, "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True},
            ]

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for frame in frames:
            self.wfile.write((json.dumps(frame) + "\n").encode())
            self.wfile.flush()


def main() -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), MockOllama)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    from core.brain import Brain

    brain = Brain()
    brain.host = f"http://127.0.0.1:{port}"
    brain.model = "mock:1"
    brain.native_ok = True
    brain.json_mode = False

    events: list[tuple[str, dict]] = []
    answer = brain.respond(
        "what time is it",
        lambda e, d: events.append((e, d)),
        lambda name, args: True,
    )

    kinds = [e[0] for e in events]
    tokens = "".join(d.get("text", "") for e, d in events if e == "token")
    tool_events = [d for e, d in events if e == "tool"]

    # Replay the HUD's rendering rules: tokens append, discard clears the bubble.
    shown = ""
    for event, data in events:
        if event == "token":
            shown += data.get("text", "")
        elif event == "discard":
            shown = ""

    print("events   :", kinds)
    print("answer   :", answer)
    print("shown    :", shown)
    print("tools    :", [t["name"] for t in tool_events])
    print("requests :", len(REQUESTS))

    checks = {
        "two model calls": len(REQUESTS) == 2,
        "tool schema sent": bool(REQUESTS and REQUESTS[0].get("tools")),
        "tool dispatched": any(t["name"] == "get_time" for t in tool_events),
        "result returned to model": any(e[0] == "tool_result" for e in events),
        "tool message appended": any(m.get("role") == "tool" for m in REQUESTS[-1]["messages"]),
        "answer streamed": answer == "It is mock noon." and shown == "It is mock noon.",
    }
    ok = all(checks.values())
    for name, passed in checks.items():
        print(("  PASS  " if passed else "  FAIL  ") + name)
    httpd.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
