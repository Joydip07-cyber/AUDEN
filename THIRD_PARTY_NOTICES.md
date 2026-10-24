# Third-party notices

AUDEN itself is MIT licensed (see `LICENSE`). It uses or downloads the
following components. None of them are modified by this project.

## Runtime

- **Python** — Python Software Foundation License. The frozen Windows build
  embeds the Python runtime.
- **psutil** — BSD 3-Clause. Used for CPU, memory, disk and battery telemetry.
- **Ollama** — MIT License. AUDEN reuses an existing Ollama installation or
  downloads the official Windows archive from
  <https://github.com/ollama/ollama/releases> on first run. Ollama is not
  bundled inside the AUDEN installer.
- **Qwen3 model weights** — provided by the Qwen team under the licence stated
  on the model card for the tag you choose. The model is downloaded by Ollama
  on first run and is not bundled with AUDEN.

## Build and packaging

- **PyInstaller** — GPL-2.0-or-later with the PyInstaller bootloader exception.
  It is used only to produce the frozen application.
- **Inno Setup** — used only to compile the Windows installer. It is not
  distributed with AUDEN.

## User interface

- All HTML, CSS, JavaScript and the WebGL orb shader are original to this
  project. No third-party JavaScript libraries are bundled.
- The interface uses the fonts already installed on Windows (Segoe UI,
  Cascadia Mono, Consolas). No font files are redistributed.
- AUDEN's HUD runs inside the Edge (Chromium) browser installed on Windows.
  Edge/Chromium is not redistributed with AUDEN.

## External services

The assistant can call public services when you ask it to:

- `wttr.in` for weather.
- A web search endpoint and arbitrary URLs for web search/fetch.
- Ollama's local API on `127.0.0.1`.

See `PRIVACY.md` for details.
