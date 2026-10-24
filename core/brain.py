"""The cognitive core: a streaming Ollama agent loop with tool use and an
offline reflex layer so the assistant stays useful when the model is absent.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from . import browser as browsers
from . import memory, tools
from .config import cfg

Emit = Callable[[str, dict], None]
Confirm = Callable[[str, dict], bool]

# Questions that should switch the assistant into code mode rather than the
# short spoken-butler style. Kept deliberately narrow to avoid firing on
# "open the code folder" style commands.
CODE_WORDS = re.compile(
    r"\b(python|javascript|js|typescript|ts|html|css|sql|java|c\+\+|c#|rust|golang|"
    r"bash|powershell|regex|algorithm|function|class|snippet|coding|script|program|"
    r"compile|debug|refactor|api|json|yaml|markdown)\b", re.I)
CODE_VERBS = re.compile(
    r"\b(write|show|give|make|create|build|fix|explain|review|refactor|debug|implement|"
    r"generate|convert|optimi[sz]e|why|how|can you|could you)\b", re.I)

CODE_INSTRUCTION = (
    "Code mode: the user is asking for code. Put the complete, runnable code in a single "
    "fenced block tagged with its language, with real imports and no ellipses or placeholders. "
    "At most two short sentences around it. Show the code in your reply; only call write_file "
    "if the user explicitly asks to save or create a file. Never claim you cannot write or show code."
)


def wants_code(text: str) -> bool:
    t = (text or "").lower()
    if "```" in t:
        return True
    return bool(CODE_WORDS.search(t)) and bool(CODE_VERBS.search(t) or "?" in t)

OFFLINE_LINE = (
    "My cognitive core is offline, {name}. Ollama is not responding on {host}, "
    "so only reflex commands are available. Run setup to bring me back."
)


class Brain:
    def __init__(self) -> None:
        self.host = str(cfg("brain", "host")).rstrip("/")
        self.model = str(cfg("brain", "model"))
        self.fallbacks = list(cfg("brain", "fallback_models", default=[]) or [])
        self.history: list[dict] = memory.recent_messages(10)
        self.json_mode = str(cfg("brain", "tool_mode", default="auto")).lower() == "json"
        self.native_ok = True
        self._lock = threading.Lock()
        self._last_check = 0.0
        self._available = False
        self.models: list[str] = []
        self.warmed = False

        # Provider: "ollama" (default, native tool calling) or "openai"
        # (any OpenAI-compatible server: LM Studio, llama.cpp, vLLM, OpenAI, Groq...).
        self.provider = str(cfg("brain", "provider", default="ollama")).lower()
        oa = cfg("brain", "openai", default={}) or {}
        self.base_url = str(oa.get("base_url", "http://127.0.0.1:1234/v1")).rstrip("/")
        self.api_key = str(oa.get("api_key", "local"))
        if self.provider == "openai" and oa.get("model"):
            self.model = str(oa["model"])

    # ------------------------------------------------------------------ #
    # discovery
    # ------------------------------------------------------------------ #
    def _get(self, path: str, timeout: float = 3.0) -> dict | None:
        try:
            with urllib.request.urlopen(f"{self.host}{path}", timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            return None

    def probe(self, force: bool = False) -> bool:
        if not force and time.time() - self._last_check < 8:
            return self._available
        self._last_check = time.time()
        if self.provider == "openai":
            return self._probe_openai()
        data = self._get("/api/tags", timeout=2.5)
        if data is None:
            if cfg("brain", "auto_fallback", default=False) and self._probe_openai():
                self.provider = "openai"
                return True
            self._available = False
            return False
        self.models = [m.get("name", "") for m in data.get("models", [])]
        if self.model not in self.models:
            chosen = next((m for m in self.fallbacks if m in self.models), None)
            if not chosen and self.models:
                # No configured model present: use whatever is installed rather than going dark.
                chosen = self.models[0]
            if chosen:
                self.model = chosen
        self._available = bool(self.models) and self.model in self.models
        return self._available

    def status(self) -> dict:
        ok = self.probe(force=True)
        return {
            "online": ok,
            "provider": self.provider,
            "model": self.model,
            "host": self.base_url if self.provider == "openai" else self.host,
            "models": self.models,
            "json_mode": self.json_mode,
            "history": len(self.history),
            "warmed": self.warmed,
        }

    def warmup(self) -> None:
        """Load the model and cache the system+tools prefix before the first question."""
        if not self.probe(force=True):
            return
        if self.provider == "openai":
            return  # first request warms the server; avoid burning tokens
        try:
            payload = json.dumps({
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self.system_prompt()},
                    {"role": "user", "content": "Reply with the single word: ready"},
                ],
                "stream": False,
                "keep_alive": cfg("brain", "keep_alive", default="30m"),
                "tools": tools.specs(),
                "options": {
                    "num_ctx": int(cfg("brain", "num_ctx", default=2048)),
                    "num_predict": 4,
                    "temperature": 0.0,
                },
            }).encode()
            req = urllib.request.Request(f"{self.host}/api/chat", data=payload,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=600).read()
            self.warmed = True
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # prompt
    # ------------------------------------------------------------------ #
    def system_prompt(self) -> str:
        name = cfg("identity", "user_name", default="sir")
        facts = memory.search_facts("user preferences projects schedule", limit=6)
        fact_block = ("\nKnown facts:\n" + "\n".join(f"- {f}" for f in facts)) if facts else ""
        info = browsers.detect()
        browser_line = f" Default browser: {info['name']}." if info else ""
        # Keep this text stable so the model's prompt cache survives between turns.
        return (
            f"{cfg('identity', 'persona')}\n"
            f"The user is {name}. Today's date and time are unknown until you call get_time.{fact_block}\n"
            f"Workspace folder: {tools.ROOT}. User home: {Path.home()}.{browser_line}\n\n"
            f"You can act on this computer with these tools: {tools.names()}.\n\n"
            "Rules:\n"
            "- Call a tool whenever it would give a real answer; never invent data such as weather, files or system stats.\n"
            "- For questions about the machine's current state, always call the tool instead of reusing earlier figures.\n"
            "- For actions, call the tool and then confirm briefly what you did.\n"
            "- Keep spoken replies to 1-2 sentences unless detail is requested. No markdown in normal replies (code mode is the exception): no lists, no emoji.\n"
            "- When creating files use a path relative to the workspace, e.g. 'notes.txt'. Use 'Desktop/name' for the Desktop.\n"
            "- If a tool fails, say so plainly and suggest the next step.\n"
            "- Use 'remember' when the user shares a lasting preference or fact."
        )

    def _messages(self, text: str, code_mode: bool = False) -> list[dict]:
        msgs = [{"role": "system", "content": self.system_prompt()}]
        if code_mode:
            msgs.append({"role": "system", "content": CODE_INSTRUCTION})
        history = self.history[-4:] if code_mode else self.history[-6:]
        limit = 400 if code_mode else 600
        for item in history:
            if item.get("content"):
                msgs.append({"role": item["role"], "content": item["content"][:limit]})
        if self.json_mode:
            msgs.append({"role": "system", "content": (
                "To use a tool, reply with ONLY a json object on one line: "
                '{"tool": "<name>", "args": {...}}. To answer, reply in plain text.'
            )})
        msgs.append({"role": "user", "content": text})
        return msgs

    # ------------------------------------------------------------------ #
    # transport
    # ------------------------------------------------------------------ #
    def _chat(self, messages: list[dict], emit: Emit, stream: bool,
              allow_tools: bool, max_tokens: int | None = None) -> tuple[str, list[dict]]:
        if self.provider == "openai":
            return self._chat_openai(messages, emit, stream, allow_tools, max_tokens)
        budget = int(cfg("brain", "max_tokens", default=420)) if max_tokens is None else max_tokens
        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "keep_alive": cfg("brain", "keep_alive", default="30m"),
            "options": {
                "temperature": float(cfg("brain", "temperature", default=0.55)),
                "num_ctx": int(cfg("brain", "num_ctx", default=4096)),
                "num_predict": budget,
                "top_p": 0.9,
                "repeat_penalty": 1.08,
            },
        }
        if allow_tools and not self.json_mode and self.native_ok:
            body["tools"] = tools.specs()

        payload = json.dumps(body).encode()
        req = urllib.request.Request(f"{self.host}/api/chat", data=payload,
                                     headers={"Content-Type": "application/json"})
        content_parts: list[str] = []
        tool_calls: list[dict] = []
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                if not stream:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
                    msg = data.get("message", {})
                    return msg.get("content", ""), msg.get("tool_calls") or []
                for raw in resp:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        chunk = json.loads(raw)
                    except Exception:
                        continue
                    msg = chunk.get("message") or {}
                    piece = msg.get("content") or ""
                    if piece:
                        content_parts.append(piece)
                        emit("token", {"text": piece})
                    for call in msg.get("tool_calls") or []:
                        tool_calls.append(call)
                    if chunk.get("done"):
                        break
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            self._last_error = detail
            if "tools" in detail.lower() and "support" in detail.lower() and self.native_ok:
                self.native_ok = False
                self.json_mode = True
                emit("notice", {"text": "This model lacks native tool calling; using the JSON protocol."})
                return self._chat(messages, emit, stream, allow_tools, max_tokens)
            raise RuntimeError(detail or f"HTTP {exc.code}") from exc
        return "".join(content_parts), tool_calls

    # ------------------------------------------------------------------ #
    # OpenAI-compatible transport (LM Studio, llama.cpp, vLLM, OpenAI, Groq)
    # ------------------------------------------------------------------ #
    def _openai_request(self, path: str, body: dict | None = None,
                        timeout: float = 5.0):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
        )
        return urllib.request.urlopen(req, timeout=timeout)

    def _probe_openai(self) -> bool:
        try:
            with self._openai_request("/models", timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            self._available = False
            return False
        self.models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
        usable = [m for m in self.models if "embed" not in m.lower()]
        if self.model not in self.models:
            chosen = next((m for m in self.fallbacks if m in self.models), None) or \
                     (usable[0] if usable else None)
            if chosen:
                self.model = chosen
        self._available = bool(usable)
        return self._available

    def _chat_openai(self, messages: list[dict], emit: Emit, stream: bool,
                     allow_tools: bool, max_tokens: int | None = None) -> tuple[str, list[dict]]:
        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": float(cfg("brain", "temperature", default=0.55)),
            "max_tokens": int(cfg("brain", "max_tokens", default=420)) if max_tokens is None else max_tokens,
            "top_p": 0.9,
        }
        if allow_tools and not self.json_mode and self.native_ok:
            body["tools"] = tools.specs()

        try:
            resp = self._openai_request("/chat/completions", body, timeout=600)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            if "tool" in detail.lower() and self.native_ok:
                self.native_ok = False
                self.json_mode = True
                emit("notice", {"text": "This model lacks native tool calling; using the JSON protocol."})
                return self._chat_openai(messages, emit, stream, allow_tools)
            raise RuntimeError(detail[:300] or f"HTTP {exc.code}") from exc

        if not stream:
            with resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            msg = ((data.get("choices") or [{}])[0] or {}).get("message") or {}
            calls = []
            for idx, tc in enumerate(msg.get("tool_calls") or []):
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                calls.append({"id": tc.get("id") or f"call_{idx}",
                              "function": {"name": fn.get("name", ""), "arguments": args}})
            return msg.get("content") or "", calls

        content_parts: list[str] = []
        acc: dict[int, dict] = {}
        with resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload in ("[DONE]", ""):
                    break
                try:
                    chunk = json.loads(payload)
                except Exception:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content") or ""
                if piece:
                    content_parts.append(piece)
                    emit("token", {"text": piece})
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index") or 0)
                    slot = acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]

        calls = []
        for idx in sorted(acc):
            slot = acc[idx]
            try:
                args = json.loads(slot["args"] or "{}")
            except Exception:
                args = {}
            calls.append({"id": slot["id"] or f"call_{idx}",
                          "function": {"name": slot["name"], "arguments": args}})
        return "".join(content_parts), calls

    def _msg_assistant_tools(self, calls: list[dict]) -> dict:
        if self.provider == "openai":
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": c.get("id") or "call_0", "type": "function",
                     "function": {"name": c["function"]["name"],
                                  "arguments": json.dumps(c["function"].get("arguments") or {})}}
                    for c in calls
                ],
            }
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": c["function"]["name"],
                                         "arguments": c["function"].get("arguments") or {}}}
                           for c in calls],
        }

    def _msg_tool_result(self, call: dict, result: str) -> dict:
        if self.provider == "openai":
            return {"role": "tool", "tool_call_id": call.get("id") or "call_0", "content": result}
        return {"role": "tool", "content": result}

    # ------------------------------------------------------------------ #
    # main entry
    # ------------------------------------------------------------------ #
    def respond(self, text: str, emit: Emit, ask_confirm: Confirm) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        with self._lock:
            if not self.probe():
                reply = self.reflex(text, ask_confirm) or OFFLINE_LINE.format(
                    name=cfg("identity", "user_name", default="sir"), host=self.host)
                emit("token", {"text": reply})
                self._remember_turn(text, reply)
                return reply

            emit("state", {"state": "thinking"})
            code_mode = wants_code(text)
            budget = int(cfg("brain", "code_max_tokens", default=900)) if code_mode else None
            messages = self._messages(text, code_mode)
            answer = ""
            for step in range(5):
                try:
                    content, calls = self._chat(messages, emit, stream=True, allow_tools=True,
                                                max_tokens=budget)
                except Exception as exc:
                    reply = (self.reflex(text, ask_confirm) or
                             f"I lost contact with my cognitive core ({str(exc)[:120]}).")
                    emit("discard", {})
                    emit("token", {"text": reply})
                    self._remember_turn(text, reply)
                    return reply

                if not calls:
                    answer = content.strip()
                    if self.json_mode:
                        parsed = self._parse_json_call(answer)
                        if parsed:
                            calls = [parsed]
                            answer = ""
                    if not calls:
                        break

                if content.strip():
                    emit("discard", {})
                for call in calls:
                    fn = (call or {}).get("function") or {}
                    name = fn.get("name") or (call.get("name") if isinstance(call, dict) else "")
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args or "{}")
                        except Exception:
                            args = {}
                    if not name:
                        continue
                    call = {"id": call.get("id") or f"call_{step}_{len(messages)}",
                            "function": {"name": name, "arguments": args}}
                    emit("tool", {"name": name, "args": args, "step": step + 1})
                    emit("state", {"state": "working"})
                    result = None
                    if tools.needs_confirm(name) and not ask_confirm(name, args):
                        result = "The user declined this action."
                        emit("tool_result", {"name": name, "result": result, "ok": False})
                    else:
                        result = tools.run(name, args)
                        emit("tool_result", {"name": name, "result": result,
                                             "ok": not result.lower().startswith(
                                                 ("unknown", "error", "could not", "failed"))})
                    emit("state", {"state": "thinking"})
                    if self.json_mode:
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": f"TOOL RESULT ({name}): {result}"})
                    else:
                        messages.append(self._msg_assistant_tools([call]))
                        messages.append(self._msg_tool_result(call, result))

            if not answer:
                follow_up = ("Now show the complete final code in one fenced block, with at most one "
                             "short sentence." if code_mode
                             else "Now answer me in one or two sentences.")
                try:
                    answer, _ = self._chat(
                        messages + [{"role": "user", "content": follow_up}],
                        emit, stream=False, allow_tools=False, max_tokens=budget)
                except Exception:
                    answer = "I completed that, though I could not compose a summary."
            answer = self._clean(answer)
            if not answer:
                answer = "Done."
            self._remember_turn(text, answer)
            emit("state", {"state": "idle"})
            return answer

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _parse_json_call(self, text: str) -> dict | None:
        match = re.search(r"\{.*\}", text or "", re.S)
        if not match:
            return None
        try:
            obj = json.loads(match.group(0))
        except Exception:
            return None
        if isinstance(obj, dict) and obj.get("tool"):
            return {"function": {"name": obj["tool"], "arguments": obj.get("args") or obj.get("arguments") or {}}}
        return None

    @staticmethod
    def _clean(text: str) -> str:
        """Tidy spoken prose without ever destroying a code block."""
        text = (text or "").strip()
        if not text:
            return ""
        parts = re.split(r"(```.*?```)", text, flags=re.S)
        out: list[str] = []
        for part in parts:
            if part.startswith("```"):
                out.append(part.strip("\n"))
                continue
            part = re.sub(r"(?m)^\s*[-*]\s+", "", part)
            part = re.sub(r"[*_#`]+", "", part)
            out.append(part.strip("\n"))
        cleaned = "\n".join(p for p in out if p.strip())
        return re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    def _remember_turn(self, user_text: str, reply: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        self.history = self.history[-12:]
        memory.add_message("user", user_text)
        memory.add_message("assistant", reply)

    def reset(self) -> None:
        self.history = []
        memory.clear_messages()

    # ------------------------------------------------------------------ #
    # offline reflexes
    # ------------------------------------------------------------------ #
    def reflex(self, text: str, ask_confirm: Confirm | None = None) -> str | None:
        t = text.lower().strip().rstrip("?.!")

        def act(name: str, *args) -> str:
            if tools.needs_confirm(name) and ask_confirm is not None and not ask_confirm(name, {}):
                return "The user declined that action."
            return getattr(tools, name)(*args)
        if re.search(r"\b(what|what's) (is )?the time|what time is it|current time\b", t):
            return tools.get_time()
        if re.search(r"\b(date|what day|today's date)\b", t) and len(t) < 60:
            return tools.get_time()
        if "weather" in t or "temperature outside" in t:
            m = re.search(r"(?:weather|forecast) (?:in|for|at) ([a-z\s]+)", t)
            return tools.get_weather(m.group(1).strip() if m else "")
        if re.match(r"^(open|launch|start) ", t):
            return tools.open_app(re.sub(r"^(open|launch|start)\s+", "", t))
        if re.search(r"volume up|louder|turn it up", t):
            return tools.media_control("volume_up")
        if re.search(r"volume down|quieter|turn it down", t):
            return tools.media_control("volume_down")
        if re.search(r"\bmute\b", t):
            return tools.media_control("mute")
        if re.search(r"\b(pause|resume|play)\b", t):
            return tools.media_control("play_pause")
        if "screenshot" in t or "screen shot" in t:
            return tools.screenshot()
        if "lock" in t and ("pc" in t or "computer" in t or "screen" in t):
            return act("lock_pc")
        if re.search(r"\b(cpu|ram|memory|battery|disk|system status|how are you running)\b", t):
            return tools.system_status()
        if re.match(r"^remember (that )?", t):
            return tools.remember(re.sub(r"^remember (that )?", "", t))
        if re.search(r"^(search|google|look up) ", t):
            return tools.web_search(re.sub(r"^(search( the web)?( for)?|google|look up)\s+", "", t))
        if re.match(r"^[\d\s().+\-*/^%]+$", t) and len(t) > 2:
            return tools.calculate(t)
        if re.search(r"\b(who are you|what are you)\b", t):
            return ("I am AUDEN, your systems assistant. My cognitive core is offline at the moment, "
                    "but my reflex systems are still at your service, sir.")
        if re.search(r"^(hello|hi|hey|good morning|good evening)\b", t):
            return "Good to hear from you, sir. My reflex systems are online; the cognitive core is still waking up."
        return None
