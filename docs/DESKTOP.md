# SpaceZenith-Sim for macOS

The desktop build embeds the Ground, Platform and GPU services inside one
Electron application. It binds every service to `127.0.0.1`, creates its own
ports per launch, and does not require Docker or a system Python installation.

## Development

Install the regular project dependencies first:

```bash
uv sync --all-groups
cd web
pnpm install
pnpm desktop:dev
```

`desktop:dev` launches the three services from the repository virtual
environment and a local Next.js dev server. The app uses a temporary set of
localhost ports, so it can run alongside the normal multi-terminal setup.

## Build the Apple Silicon DMG

Build on an Apple Silicon Mac with Xcode Command Line Tools available:

```bash
cd web
pnpm install
pnpm desktop:dist
```

The DMG is written to `web/release/`. The build first makes a frozen Python
runtime with PyInstaller, then packages it together with the Next.js standalone
server and Electron Chromium runtime.

The first release is intentionally unsigned and unnotarized. macOS may require
opening **System Settings → Privacy & Security** and choosing **Open Anyway**.

## Data, logs and model providers

The app keeps all persistent state under:

```text
~/Library/Application Support/SpaceZenith-Sim/
```

This includes SQLite, mission artifacts, service logs, and
`desktop-settings.json`. The settings dialog configures Ollama/LLM and YOLO
providers. Saving settings restarts only the embedded GPU service. Keys are
stored locally with user-only file permissions and are never added to mission
events or SQLite.

The App does not bundle Ollama or model weights. For an existing local Ollama,
set its endpoint to `http://127.0.0.1:11434` and choose an installed vision
model in the desktop settings.
