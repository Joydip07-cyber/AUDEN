# Privacy

AUDEN is a local-first desktop assistant. It does not require an account and
does not include telemetry, analytics or advertising.

## What stays on your PC

- Conversations and remembered facts: SQLite database in
  `%LOCALAPPDATA%\AUDEN\auden.db` for installed builds, or `data\auden.db` in a
  source checkout.
- Settings: `%LOCALAPPDATA%\AUDEN\config.json`.
- Screenshots you ask for: `%LOCALAPPDATA%\AUDEN\screenshots\`.
- The local AI model and Ollama runtime, when AUDEN installs a private engine:
  `%LOCALAPPDATA%\AUDEN\models\` and `%LOCALAPPDATA%\AUDEN\runtime\`.
- Logs: `%LOCALAPPDATA%\AUDEN\logs\`.

Uninstalling AUDEN removes the program files but keeps this user data so you
can reinstall without losing your memory. Delete `%LOCALAPPDATA%\AUDEN`
manually for a full reset.

## Network connections

AUDEN only makes outbound connections when a feature needs them:

- **First run:** downloads the Ollama Windows archive from GitHub Releases and
  the selected model from the Ollama registry, unless an existing Ollama
  installation is reused.
- **Weather:** sends the city name to `wttr.in`.
- **Web search / fetch:** sends the query or URL to the configured public
  service or website.
- **Local AI:** talks to Ollama on `127.0.0.1` (or a private port). The model
  runs on your hardware.
- **Browser launch:** opens links in the browser Windows reports as your
  default. AUDEN does not send browsing data anywhere.

No conversation content is uploaded by AUDEN itself.

## Voice input

The HUD uses the browser's Web Speech API inside the Edge app window. Depending
on your Windows/Edge configuration, speech recognition may be processed by
Microsoft's cloud service. If you need fully offline voice input, disable voice
input in the settings or use the console mode with a local speech stack of your
choice. Text-to-speech uses the Windows voices installed on your PC.

## Local server

The HUD server binds only to `127.0.0.1` and requires a random token generated
at launch. It is not reachable from other machines unless you deliberately
change the bind address or proxy it. Do not expose port 8765 to a network.

## Contact

For privacy questions, open an issue in the project repository.
