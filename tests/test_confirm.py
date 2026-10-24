"""End-to-end test of the approval handshake (SSE confirm -> POST /api/confirm).

    python tests/test_confirm.py
"""
from __future__ import annotations

import http.client
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TARGET = ROOT / "data" / "tmp_test" / "approved.txt"
TARGET.parent.mkdir(parents=True, exist_ok=True)
TARGET.unlink(missing_ok=True)


class MockOllama(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        return

    def do_GET(self):
        raw = json.dumps({"models": [{"name": "mock:1"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/generate":
            raw = json.dumps({"response": ""}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        saw_result = any(m.get("role") == "tool" for m in body.get("messages", []))
        if not saw_result:
            frames = [{"message": {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "write_file",
                              "arguments": {"path": str(TARGET), "content": "approved"}}}]}, "done": True}]
        else:
            frames = [{"message": {"role": "assistant", "content": "Written, sir."}, "done": True}]
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for frame in frames:
            self.wfile.write((json.dumps(frame) + "\n").encode())
            self.wfile.flush()


def main() -> int:
    mock = ThreadingHTTPServer(("127.0.0.1", 0), MockOllama)
    threading.Thread(target=mock.serve_forever, daemon=True).start()

    from core import server

    server.BRAIN.host = f"http://127.0.0.1:{mock.server_address[1]}"
    server.BRAIN.model = "mock:1"
    server.BRAIN.native_ok = True
    server.BRAIN.json_mode = False

    httpd = server.create(0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    conn.request("POST", "/api/chat", body=json.dumps({"text": "write that file"}),
                 headers={"Content-Type": "application/json", "X-Auden-Token": server.TOKEN})
    resp = conn.getresponse()

    events: list[tuple[str, dict]] = []
    buf = ""
    confirm_seen = False
    answered = False
    deadline = time.time() + 25

    while time.time() < deadline:
        try:
            chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(64)
        except Exception:
            break
        if not chunk:
            break
        buf += chunk.decode("utf-8", "replace")
        while "\n\n" in buf:
            frame, buf = buf.split("\n\n", 1)
            name, data = "message", None
            for line in frame.split("\n"):
                if line.startswith("event: "):
                    name = line[7:].strip()
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                    except Exception:
                        data = None
            if data is None:
                continue
            events.append((name, data))
            if name == "confirm" and not confirm_seen:
                confirm_seen = True
                body = json.dumps({"id": data["id"], "approved": True}).encode()
                c2 = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                c2.request("POST", "/api/confirm", body=body,
                           headers={"Content-Type": "application/json", "X-Auden-Token": server.TOKEN})
                c2.getresponse().read()
                c2.close()
            if name == "done":
                answered = True

    kinds = [e[0] for e in events]
    print("events      :", kinds)
    print("confirm     :", [d for e, d in events if e == "confirm"])
    print("file exists :", TARGET.exists())
    print("file body   :", TARGET.read_text() if TARGET.exists() else "-")
    print("answer      :", [d.get("text") for e, d in events if e == "done"])

    checks = {
        "approval requested": confirm_seen,
        "file written after approval": TARGET.exists() and TARGET.read_text() == "approved",
        "stream completed": answered,
        "answer returned": any(e == "done" and "Written" in (d.get("text") or "") for e, d in events),
    }
    ok = all(checks.values())
    for name, passed in checks.items():
        print(("  PASS  " if passed else "  FAIL  ") + name)

    httpd.shutdown()
    mock.shutdown()
    if TARGET.exists():
        TARGET.unlink()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
