# SpaceZenith-Sim 桌面版

The desktop build embeds Ground, Platform, Optical and its UI inside one Electron
application. It is the only supported delivery and runtime mode: the renderer and
Python services are not deployed as separate frontend/backend services. The local
services bind to `127.0.0.1`; Jetson runs the L1 (L1A/L1B/STAC) and AI payload.
Only the Platform GTX result listener is opened on the configured trusted LAN
address. The desktop App does not require Docker or a system Python installation.
On macOS, both built-in and customer L0/L1 versions run through the
application-managed Seatbelt executor. Customer code has no network, no user
data-directory access and no host-Python fallback. Windows keeps custom
processors fail-closed until its native secure runner is available; built-in
L0/L1 processing remains available.

## Development

Install the regular project dependencies first:

```bash
uv sync --all-groups
cd web
pnpm install
pnpm desktop:dev
```

`desktop:dev` launches the local App services from the repository virtual
environment and its embedded Next.js renderer. It uses temporary localhost
ports and does not require a separately deployed Web server.

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

Windows 运行时不需要系统 Python 或本地模型。它会启动嵌入的 Ground、Platform、Optical
与界面运行时，所有本地端口仅绑定 `127.0.0.1`。Ollama 是 Jetson 上的本地外部服务。

Windows 用户数据、日志和设置由 Electron 存入标准 `%APPDATA%\\SpaceZenith-Sim\\`
目录；可在应用设置的“关于”页打开数据与日志目录。

## Data, logs and model providers

The app keeps all persistent state under:

```text
~/Library/Application Support/SpaceZenith-Sim/
```

This includes SQLite, mission artifacts, service logs, and
`desktop-settings.json`. The settings dialog configures the Jetson GPU Payload
and its LLM model. Changing Jetson connectivity restarts the App service stack;
the App never starts a local GPU service or local Ollama fallback. Keys are
stored locally with user-only file permissions and are never added to mission
events or SQLite.

The App does not bundle Ollama or model weights. In Jetson mode Ollama must
remain at `http://127.0.0.1:11434`; use Settings → AI to install a recommended
vision model or enter an Ollama model tag. The SSH password is used only for
that active desktop session and is never saved. Settings then lists only
vision-capable models through the Jetson GPU service. See [Jetson GPU Payload](../deploy/jetson/README.md).

## Jetson GPU 模式

1. 按 [Jetson GPU Payload](../deploy/jetson/README.md) 构建、导入并启动 Jetson GPU API 镜像。
2. 在 Settings → AI 填写 Jetson LAN 地址和 Jetson 可访问的 Mac LAN 地址。
3. 保存后重新打开 Settings，选择 Jetson 返回的视觉模型。

Jetson 未连接、版本不一致、Ollama 无视觉模型或自定义 L1 Docker runtime 不可用时，
App 仍可管理场景，但 L1/AI 阶段会阻塞，绝不自动改用本机 GPU。
