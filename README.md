# SpaceZenith-Sim

独立、可拆分部署的软件在环（SIL）系统，模拟地面站、数传、星务平台、光学
载荷、Virtual GTX 与 GPU 载荷之间的完整任务闭环。

V1 真实实现六段人工单步任务、光学 RAW/L0/L1A/L1B/STAC、轨姿推演、二进制
链路、故障注入、选择重传和独立节点存储。红外仍是占位；YOLO 与 LLM 提供真实
HTTP 适配器，未配置时第五步阻塞，不生成虚假模型结果。

## 系统边界

```text
Next.js Web -> Ground API --SIMF uplink--> OBC Node
                                      |--Payload Bus--> Optical Node --RAW/L0-->
                                      |--Virtual GTX--> GPU/Jetson Node --L1/AI-->
Next.js Web <- Ground API <--SIMF downlink-- OBC Node
```

- 地面站是唯一公开 API；星务、光学和 GPU 只开放内部健康/管理接口。
- Ground、Platform、Optical、GPU 各有独立数据卷，产品必须经过 TCP 分帧链路逐字节传输。
- GTX 模拟数据格式、带宽、时延、背压、CRC、丢帧和恢复，不模拟 PHY/SerDes。
- 数传采用 CCSDS Space Packet、TC/AOS、CFDP 语义对齐子集，不声明标准一致性。
- 场景 TLE、传感器参数、链路参数和随机 seed 都是版本化配置。

## 快速运行

环境要求：Docker Compose；或 Python 3.12、uv、Node.js 22+、pnpm。

```bash
cp .env.example .env
docker compose up --build
```

打开：

- 地面站：<http://localhost:3000>
- Ground OpenAPI：<http://localhost:8000/docs>

## 桌面版（macOS 与 Windows）

Electron 桌面版会在一个 App 内自动启动 Ground、Platform、Optical、GPU 与 Web，首版目标为
Apple Silicon macOS 与 Windows 10/11 x64。开发和打包说明见
[docs/DESKTOP.md](docs/DESKTOP.md)。Windows 安装程序须在 Windows x64 本机构建：

```powershell
cd web
pnpm desktop:dist:win
```

Web 使用 `?tab=ground|platform|optical|gpu` 切换地面站、星务平台、光学载荷和
GPU Payload。只有地面站页提供任务控制；其他节点页属于仿真观察平面，下载的
节点本地文件会明确标记为“未通过星地下传”。

界面首次加载会创建暂停的默认场景。点击“新建观测任务”选择 YOLO 或 LLM 后，
系统只规划窗口并停在 `initialized`；随后连续六次点击主“单步”按钮，每次只推进
一个宏阶段并自动暂停。可以在对应阶段前注入确定性链路故障。

## 本地开发

```bash
uv sync --all-groups
cd web && pnpm install && cd ..
uv run alembic upgrade head
```

按顺序启动五个终端：

```bash
SAT_SIM_DATA_DIR=runtime-data/gpu SAT_SIM_GROUND_HTTP_URL=http://127.0.0.1:8000 uv run uvicorn sat_simulation.services.gpu:app --port 8002
SAT_SIM_DATA_DIR=runtime-data/optical SAT_SIM_GROUND_HTTP_URL=http://127.0.0.1:8000 SAT_SIM_PLATFORM_PAYLOAD_RESULT_HOST=127.0.0.1 uv run uvicorn sat_simulation.services.optical:app --port 8003
SAT_SIM_DATA_DIR=runtime-data/ground SAT_SIM_PLATFORM_UPLINK_HOST=127.0.0.1 SAT_SIM_PLATFORM_HTTP_URL=http://127.0.0.1:8001 SAT_SIM_GPU_HTTP_URL=http://127.0.0.1:8002 uv run uvicorn sat_simulation.services.ground:app --port 8000
SAT_SIM_DATA_DIR=runtime-data/platform SAT_SIM_GROUND_DOWNLINK_HOST=127.0.0.1 SAT_SIM_GROUND_HTTP_URL=http://127.0.0.1:8000 SAT_SIM_GPU_GTX_HOST=127.0.0.1 SAT_SIM_OPTICAL_PAYLOAD_HOST=127.0.0.1 uv run uvicorn sat_simulation.services.platform:app --port 8001
cd web && pnpm dev
```

命令行闭环：

```bash
uv run python scripts/demo_mission.py
```

## 主要公共 API

- `POST /api/scenes/validate|import`：预检并导入 GeoTIFF/PNG/JPEG 光学输入。
- `GET /api/processors/templates`、`GET /api/processors/{id}/source`、`POST /api/processors/workspace`：处理器工作区模板、源码查看与应用内自定义版本保存。
- `POST/GET /api/processors`：严格校验、注册和选择 Python 3.12 ZIP 处理器。
- `POST/GET /api/scenarios`：创建或查看版本化场景。
- `POST /api/scenarios/{id}/control`：运行、暂停、单步、倍率和新 run。
- `POST/GET /api/missions`、`GET /api/missions/{id}`：任务与完整事件/产品。
- `POST /api/missions/{id}/advance`：幂等推进一个宏阶段，立即返回 `202`。
- `GET /api/missions/{id}/result`：仅在第六步结果包到达地面后可用。
- `GET /api/providers/health`：GPU Provider 动态配置状态。
- `POST/DELETE /api/scenarios/{id}/faults`：确定性故障规则。
- `GET /api/transfers`：GTX、上行和下行事务。
- `GET /api/products/{id}/manifest`、`GET /api/artifacts/{id}`：地面产品。
- `GET /api/events/stream?run_id=...`：SSE 事件流。
- `GET /api/missions/{id}/nodes/{node}`：节点调试快照与本地文件目录。
- `GET /api/missions/{id}/protocol/transactions`：协议事务、正文摘要和帧追踪。
- `GET /api/protocol/stream?run_id=...`：实时协议事务与帧 SSE。

OpenAPI 类型可重复生成：

```bash
cd web && pnpm generate:api
```

## 验证

```bash
make test
make lint
make web-check
docker compose config --quiet
```

测试覆盖仿真时钟、CRC32C 已知向量、协议帧、丢失/损坏/重复/乱序、TCP 选择
重传、SGP4、姿态、RAW/L0 精确重建、L1A 辅助元数据、L1B 数值误差、STAC 和
Provider 阻塞真实性、步骤幂等性和持久化重试状态。

## 目录

- `sat_simulation/common`：时钟、协议、链路、轨姿和公共模型。
- `sat_simulation/optical`：场景校验、探测器 RAW 与内置产品处理。
- `sat_simulation/processors`：自定义处理器 ZIP SDK、模板与 macOS Seatbelt/服务器 OCI 执行器。
- `sat_simulation/payload`：检测与语言 Provider 契约。
- `sat_simulation/services`：ground、platform、optical、GPU 四个独立节点进程。
- `web`：Next.js/Cesium 地面站。
- `migrations`：PostgreSQL/SQLite Alembic 迁移。
- `scenarios`：版本化演示参数。
- `docs`：架构、协议 ICD、产品定义和运行手册。

## 明确未实现

- 红外载荷仅返回 `not_implemented`。
- 未配置 YOLO/LLM 时第五步为 `blocked`；配置后可原阶段重试。
- 不包含完整传感器物理、GTX 电气特性、RF 物理层、安全加固或 CCSDS 认证。

详见 [架构](docs/ARCHITECTURE.md)、[协议 ICD](docs/PROTOCOL.md)、
[光学产品](docs/PRODUCTS.md)、[处理器 SDK](docs/PROCESSOR_SDK.md) 和 [运行手册](docs/OPERATIONS.md)。
