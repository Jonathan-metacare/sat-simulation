# SpaceZenith-Sim

SpaceZenith-Sim 是一个桌面仿真 App：在一台 Mac 或 Windows PC 上通过 **New Sat**
创建卫星、地面站与观测场景，执行端到端任务，并查看 Ground、Platform、Optical 与
GPU Payload 的仿真数据。项目只以完整 App 交付；不再支持前后端、Docker、PostgreSQL
或浏览器 Web 服务的独立部署。

## 使用 App

桌面版首次启动会自动创建本地 SQLite 数据和示例场景。通过顶部的 **New Sat** 创建
卫星、地面站与观测场景；也可在 Settings → Scene 中导入完整 YAML 场景。

- 默认 **Jetson GPU**：Mac 保留 Ground、Platform、Optical 与界面；Jetson 执行 L1
 处理（L1A/L1B/STAC）、自定义 L1 Docker 沙箱和 Ollama 视觉分析。Jetson 离线或
 版本不一致时任务 L1/AI 阶段明确阻塞，不会回退至 Mac。
- GPU 推理与 L1 处理仅由 Jetson 执行；桌面端不会启动本机 GPU 或本机 Ollama 回退。

详细使用、开发和打包方式见 [桌面版指南](docs/DESKTOP.md)。Jetson 部署方式见
[Jetson GPU Payload](deploy/jetson/README.md)。

## 构建桌面版

构建机需要 Python 3.12、uv、Node.js 22+ 与 pnpm。

```bash
uv sync --all-groups
cd web
pnpm install
pnpm desktop:dist
```

macOS Apple Silicon DMG 输出到 `web/release/`。它会构建并内置同版本 Jetson
ARM64 离线 payload，因此比纯桌面 App 约增加 380–400 MB。首版仅支持该 macOS
交付路径；Windows 安装包不内置 Jetson payload。

开发时可运行：

```bash
make desktop-dev
```

## 维护与验证

```bash
make test
make lint
make web-check
```

`web/` 仍是桌面 App 的 React/Next.js 渲染层及 Electron 打包内容；它不会作为独立
Web 服务发布。应用数据清理与备份方式见 [数据维护](docs/DATA_MAINTENANCE.md)。

## 项目结构

- `desktop/`：冻结 Python 服务的桌面入口。
- `web/`：Electron、桌面 UI、Cesium 及安装包构建配置。
- `sat_simulation/`：仿真核心、节点服务、场景和处理器逻辑。
- `deploy/jetson/`：Jetson Orin GPU Payload 的 ARM64 离线镜像构建、导入和运行配置。
- `processor-runtime/`：仅 Jetson 自定义 L1 所需的 ARM64 Docker 运行时定义。
- `scenarios/`：内置示例卫星与 GeoTIFF 场景。
- `examples/`：可导入的自定义 L0/L1 处理器示例。
- `tests/`：回归测试。
- `docs/`：桌面使用、数据维护、架构、协议、产品和处理器参考。

## 参考文档

- [桌面版指南](docs/DESKTOP.md)
- [Jetson GPU Payload](deploy/jetson/README.md)
- [数据维护](docs/DATA_MAINTENANCE.md)
- [处理器 SDK](docs/PROCESSOR_SDK.md)
- [架构](docs/ARCHITECTURE.md)、[协议](docs/PROTOCOL.md)、[产品](docs/PRODUCTS.md)
