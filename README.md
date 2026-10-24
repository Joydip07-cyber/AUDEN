# A.U.D.E.N — local desktop AI for Windows

A voice-driven assistant with an animated holographic HUD, a local language
model, and real control over your Windows machine. No account, no API key, no
cloud call: the model and your memory stay on your PC.

AUDEN runs as a frameless desktop app (Edge in `--app` mode), talks to a local
[Ollama](https://ollama.com) engine, and uses a small stdlib HTTP/SSE server to
connect the HUD to the brain.

---

## Install

Download the latest `AUDEN-Setup-<version>.exe` from the project's Releases
page and run it. The installer is per-user: it does **not** need administrator
rights and installs under `%LOCALAPPDATA%\Programs\AUDEN`.

It creates a desktop shortcut and a Start Menu entry. An optional **Start AUDEN
when I sign in** checkbox is available in the installer.

### What happens on first launch

1. The one-click setup wizard opens.
2. AUDEN looks for an Ollama engine already running on this PC. If it finds one,
   it reuses it and any suitable model already installed.
3. If no engine is available, AUDEN downloads a private Ollama runtime into its
   own folder and starts it on `127.0.0.1:11435`. Your system Ollama (if any) is
   left alone.
4. Pick a model. The wizard recommends one for your RAM and shows installed
   models first, so an existing model is never downloaded twice.
5. Enter your name, city, and whether AUDEN should speak. Finish, and the HUD
   opens.

The setup wizard can be reopened at any time:

```bat
"%LOCALAPPDATA%\Programs\AUDEN\AUDEN.exe" --setup
```

### Requirements

- Windows 10 or 11, 64-bit.
- 8 GB RAM minimum; 16 GB recommended for 8B models.
- About 5 GB of free disk space for the private engine and a 3–4B model.
- Internet access for the first setup only. After that, AUDEN runs offline.

No Python, Ollama, or other runtime needs to be installed by hand. The
installer includes AUDEN and its bundled Python runtime; the AI engine and
model are downloaded by the setup wizard.

> Builds are not currently code-signed. Windows SmartScreen may warn on first
> run. Verify the SHA-256 in `SHA256SUMS.txt` from the release if you want to
> check the download.

---

## Use it

- **Talk:** click the microphone once to arm continuous listening. Phrases
  beginning with **“Auden…”** are commands. Hold `Alt+Space` for push-to-talk;
  `Esc` stops a reply.
- **Type:** use the input dock at the bottom of the HUD.
- **Change size:** click **MINI** in the top bar or press `Alt+M` to cycle
  **full → mini → orb**. The choice is remembered across launches.
- **Mini at launch:** `AUDEN.exe --mini`.
- **Close the HUD** to stop AUDEN. The server, browser window, and any private
  Ollama process started by AUDEN are shut down. A pre-existing system Ollama
  is left running.
- Idle shutdown defaults to 30 minutes and can be changed with
  `app.idle_timeout` in `config.json`.

---

## What it can do

| Area | Examples |
| --- | --- |
| **System** | “How’s my CPU doing?”, “take a screenshot”, “lock the PC”, “turn the volume down”, “open Spotify”, “open the downloads folder” |
| **Browser** | “Open YouTube”, “open github.com”, “open Brave” — asks Windows for your default browser (Brave, Chrome, Edge, Firefox, Vivaldi, Opera) and opens links there |
| **Files** | “Find files called invoice”, “read the last 40 lines of notes.txt”, “write a file called ideas.md with …” |
| **Code** | “Write a Python function that reverses a string”, “fix this bug”, “explain this regex” — answers with a formatted code block, or saves the file if you ask |
| **Web** | “What’s the weather in Tokyo?”, “search the web for RISC-V news”, “fetch this URL and summarise it” |
| **Memory** | “Remember that I prefer tea”, “what do you remember about my project?” — stored in SQLite, survives restarts |
| **Time** | “Set a timer for 10 minutes” → spoken alert when it fires |
| **Reasoning** | Multi-step tasks: it decides which tools to call, runs them, reads the results, then answers |

Ask it something it cannot do with a tool and the local model still answers from
its own knowledge. Code requests switch into code mode automatically: a larger
output budget, fenced blocks with a **COPY** button, and no read-aloud.

---

## Safety and privacy

- The HUD server binds to `127.0.0.1` only, and every API call requires a
  per-launch session token.
- Destructive tools (`run_command`, `write_file`, `lock_pc`, `type_text`) raise
  an **AUTHORISATION REQUIRED** card and wait for approval. You can also say
  “yes” to let the model re-attempt.
- File writes are restricted to folders listed in
  `config.json → safety.write_roots`; the workspace defaults to
  `Documents\AUDEN`.
- Shell access can be disabled entirely with `"allow_shell": false`.
- Your conversations and facts live in a local SQLite database. The public
  build does **not** contain a database or a personalized config.
- AUDEN does not call a cloud model unless you explicitly configure an
  OpenAI-compatible provider.

See [PRIVACY.md](PRIVACY.md) and [SECURITY.md](SECURITY.md) for the full notes.

---

## Where your data lives

| Path | Contents |
| --- | --- |
| `%LOCALAPPDATA%\Programs\AUDEN\` | Program files, including the bundled runtime and UI |
| `%LOCALAPPDATA%\AUDEN\config.json` | Your settings |
| `%LOCALAPPDATA%\AUDEN\auden.db` | Memory, facts, and conversation history |
| `%LOCALAPPDATA%\AUDEN\logs\` | `auden.log` and the private engine's `ollama.log` |
| `%LOCALAPPDATA%\AUDEN\models\` | Models downloaded by AUDEN's private engine |
| `%LOCALAPPDATA%\AUDEN\runtime\` | The private Ollama runtime, if one was installed |
| `Documents\AUDEN\` | Default workspace for files AUDEN creates |

Uninstalling removes the program and shortcuts but **keeps
`%LOCALAPPDATA%\AUDEN`**, so your memory and models survive a reinstall. To do a
complete reset, uninstall AUDEN and delete that folder.

A source checkout uses the repository itself for `config.json` and `data/`
instead. A portable build can be made by placing an empty `portable.txt` next
to `AUDEN.exe`, or by passing `--portable`; config, data, models, and runtime
then live beside the executable.

---

## Configuration

The installed app's config is `%LOCALAPPDATA%\AUDEN\config.json`. In a source
checkout it is `config.json` in the repository root. Missing keys are filled
from sensible defaults; you only need to edit what you care about.

| Key | Meaning |
| --- | --- |
| `app.setup_complete` | Set by the wizard; `--setup` reruns it |
| `app.idle_timeout` | Seconds without a connected HUD before shutdown (default `1800`) |
| `identity.user_name` | What AUDEN calls you |
| `identity.persona` | The system prompt / personality |
| `brain.model` | Ollama model tag. Any installed model works |
| `brain.provider` | `ollama` (default) or `openai` for any OpenAI-compatible server |
| `brain.host` | Ollama address; `11434` for a system install, `11435` for AUDEN's private engine |
| `brain.fallback_models` | Models tried if the primary one is missing |
| `brain.tool_mode` / `core_tools_only` | Tool-schema strategy; core-only is faster on CPU |
| `brain.temperature` | 0 = terse and factual, 1 = chatty |
| `brain.num_ctx` / `max_tokens` / `code_max_tokens` | Context window and reply caps (lower = faster on CPU) |
| `voice.preferred_voices` | Preferred Windows speech voices; `Ryan`, `George`, and `Daniel` are British male voices |
| `voice.rate` / `pitch` | Speech speed and depth |
| `wake.words` / `wake.require_wake_word` | Wake phrases and whether every command needs one |
| `safety.allow_shell` | Set `false` to disable shell tools |
| `safety.confirm_tools` | Tools that require an approval card |
| `safety.write_roots` | Folders where files may be written |
| `safety.workspace` | Default folder for files AUDEN creates |
| `ui.start_mode` | `full`, `mini`, or `orb` |
| `location.city` / `units` | Weather defaults |

Voice, wake, and brain settings can be applied live through
`POST /api/settings`; otherwise edit the file and restart.

### Choosing a model

For an 8 GB CPU-only machine, a 3–4B model is the sweet spot. If you have more
RAM or a GPU:

```bat
ollama pull qwen3:8b
```

Then set `brain.model` to `qwen3:8b`, or choose it in the setup wizard. The
launcher falls back through `brain.fallback_models`, and if none of the
configured names exist it uses whatever model is installed rather than going
dark.

### Using an OpenAI-compatible backend

Anything that speaks the OpenAI API can drive AUDEN:

```jsonc
"brain": {
  "provider": "openai",
  "openai": {
    "base_url": "http://127.0.0.1:1234/v1",   // e.g. LM Studio
    "api_key": "local",
    "model": "qwen3-4b-instruct-2507"
  }
}
```

For a local LM Studio server: `lms server start`, then launch AUDEN. For a
cloud provider, point `base_url` at it and put your key in `api_key`. Replies
may be faster and smarter, but that traffic is no longer local.

---

## Troubleshooting

**Setup cannot download the engine or a model**
Check your internet connection and free disk space, then rerun
`AUDEN.exe --setup`. Partial engine downloads resume from where they stopped.
The private engine log is `%LOCALAPPDATA%\AUDEN\logs\ollama.log`.

**“Cognitive core offline” in the HUD**
The configured Ollama host is not reachable or the model is missing. Rerun
setup, or start the engine manually:

```bat
ollama serve
ollama pull qwen3:4b
```

**No voice output**
Click once inside the window first; browsers require a gesture before audio.
Check that the **VOICE ON** button is lit and that a British voice is installed
in Windows speech settings.

**The microphone does not work**
Edge asks for microphone permission the first time. Allow it, and make sure no
other app is holding the microphone exclusively. Typing always works.

**The HUD did not open**
AUDEN falls back to your default browser if Edge cannot create an app window.
You can also run `AUDEN.exe --no-window` and open the URL printed in
`%LOCALAPPDATA%\AUDEN\logs\auden.log`. The server only listens on
`127.0.0.1`.

**Replies are slow**
Expected on a 2-core CPU. Lower `brain.max_tokens`, keep `num_ctx` around 2048,
keep `core_tools_only` on, or pull a smaller model such as `qwen3:1.7b`.

**Start over**
Uninstall AUDEN, delete `%LOCALAPPDATA%\AUDEN`, and reinstall. This removes
your local memory and downloaded models.

---

## Build from source

### Run a checkout

Prerequisites: Python 3.10+ (tested with 3.15) and `psutil`.

```bat
python -m pip install psutil
run.bat
```

or:

```bat
python auden.py
```

A fresh checkout with no `config.json` starts the setup wizard. If you already
have a config, `python auden.py --setup` reopens it. To use a throwaway
configuration while developing, set `AUDEN_HOME` to a temporary directory.

### Build the Windows app and installer

The build uses PyInstaller for a one-folder app and Inno Setup 6 for the
per-user installer.

```bat
python -m pip install pyinstaller psutil
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

Outputs:

- `dist\AUDEN\AUDEN.exe` — one-folder application.
- `dist\installer\AUDEN-Setup-2.0.0.exe` — installer.
- `dist\installer\SHA256SUMS.txt` — installer checksum.

Useful switches: `-SkipTests`, `-SkipInstaller`, and `-Clean`. Inno Setup is
looked up in the standard per-user and machine-wide locations; override by
putting `ISCC.exe` on `PATH`.

The public installer does **not** include `config.json`, `data/`, a database,
or a private Ollama runtime. It downloads the engine and model during first-run
setup.

### Optional code signing

Set both variables before the build to sign the app and installer with
Authenticode:

```powershell
$env:AUDEN_SIGN_CERT = "C:\path\to\certificate.pfx"
$env:AUDEN_SIGN_PASSWORD = "password"
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

If `signtool.exe` is not found, the build warns and continues unsigned.

### Release checklist

1. Run `build.ps1` with tests enabled.
2. Install the generated installer on a clean Windows VM or a fresh user
   profile. Complete first-run setup, send one chat message, and uninstall.
3. Confirm the installer and app contain no `config.json`, `data/`, or
   `auden.db`.
4. Publish the installer and `SHA256SUMS.txt` to the Releases page.
5. Never upload your own `%LOCALAPPDATA%\AUDEN` folder or repository `data/`.

---

## Architecture

```
auden.py               launcher, single-instance guard, setup gating, HUD lifecycle
core/
  paths.py             source / installed / portable filesystem layout
  config.py            defaults, deep-merged config, atomic saves
  provision.py         Ollama reuse, private runtime download, model pull
  setup_server.py      temporary token-protected first-run API
  server.py            stdlib HTTP + SSE, auth, approvals, telemetry
  brain.py             Ollama streaming agent loop + offline reflex layer
  browser.py           default-browser detection and URL launch
  tools.py             22 tools exposed to the model as JSON schemas
  memory.py            SQLite facts and conversation history
  window.py            Win32 placement helpers for the Edge app window
ui/
  index.html           HUD shell
  hud.css / hud.js     holographic UI, streaming client, speech, approvals
  orb.js               WebGL arc-reactor shader (2D canvas fallback)
  setup.html/css/js    first-run wizard
assets/                icons
installer/AUDEN.iss    Inno Setup definition
AUDEN.spec             PyInstaller definition
build.ps1              tests, freeze, installer, hashes, optional signing
```

### Request flow

```
mic / text
   → Web Speech API transcription
   → POST /api/chat (SSE)
   → brain: system prompt + memories + tool schemas
   → Ollama streams tokens; the model may emit tool_calls
   → tools.py executes (approval card if sensitive)
   → results are fed back to the model
   → tokens stream to the HUD and are spoken sentence-by-sentence
   → exchange is persisted to SQLite
```

### Adding a tool

```python
# core/tools.py
@tool("play_music", "Play a track by name.",
      params={"track": {"type": "string", "description": "Song title"}},
      required=["track"])
def play_music(track: str) -> str:
    os.startfile(f"spotify:search:{track}")
    return f"Playing {track}."
```

Restart and it is immediately available to the model and visible in the
**MODULES** panel. No schema file to edit.

---

## License

MIT. See [LICENSE](LICENSE). Ollama and model licenses are covered in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
