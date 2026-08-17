# SpaceZenith-Sim 桌面版

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

## 构建 Apple Silicon DMG

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

## 构建 Windows 10/11 x64 安装程序

必须在 Windows 10 或 Windows 11 x64 机器上构建；PyInstaller 不支持从 macOS
交叉生成 Windows 服务可执行文件。构建机需要 Python 3.12、uv、Node.js 22+、pnpm
以及 Microsoft Visual C++ Redistributable（用于 Rasterio、OpenCV 等原生依赖）。

在 PowerShell 中执行：

```powershell
uv sync --all-groups
Set-Location web
pnpm install
pnpm desktop:dist:win
```

产物为 `web/release/SpaceZenith-Sim-Setup-<version>-x64.exe`。安装程序按当前用户
安装，创建开始菜单和桌面快捷方式，并提供卸载入口。首版未签名，Windows SmartScreen
可能显示未知发布者提示。升级安装会保留用户的本地任务、场景、SQLite、Cesium Token
和 AI Provider 设置。

Windows 运行时不需要 Docker、系统 Python 或本地模型。它会启动嵌入的 Ground、Platform、
GPU 和 Web 服务，所有端口仅绑定 `127.0.0.1`。Ollama/YOLO 仍是用户可选的外部服务。

Windows 用户数据、日志和设置由 Electron 存入标准 `%APPDATA%\\SpaceZenith-Sim\\`
目录；可在应用设置的“关于”页打开数据与日志目录。

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
