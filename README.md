# 星上智能计算数字孪生

独立、可拆分部署的软件在环（SIL）系统，模拟地面站、数传、星务平台、光学
载荷、Virtual GTX 与 GPU 载荷之间的完整任务闭环。

V1 真实实现六段人工单步任务、光学 RAW/L0/L1A/L1B/STAC、轨姿推演、二进制
链路、故障注入、选择重传和独立节点存储。红外仍是占位；YOLO 与 LLM 提供真实
HTTP 适配器，未配置时第五步阻塞，不生成虚假模型结果。

## 系统边界

```text
Next.js Web -> Ground API --SIMF uplink--> Platform Node
                                      Platform Node --Virtual GTX--> GPU Node
Next.js Web <- Ground API <--SIMF downlink-- Platform Node
```

- 地面站是唯一公开 API；星务和 GPU 只开放容器网络中的健康/管理接口。
- 星务、GPU、地面各有独立数据卷，产品必须经过 TCP 分帧链路逐字节传输。
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

界面首次加载会创建暂停的默认场景。点击“新建观测任务”选择 YOLO 或 LLM 后，
系统只规划窗口并停在 `initialized`；随后连续六次点击主“单步”按钮，每次只推进
一个宏阶段并自动暂停。可以在对应阶段前注入确定性链路故障。

## 本地开发

```bash
uv sync --all-groups
cd web && pnpm install && cd ..
uv run alembic upgrade head
```

按顺序启动四个终端：

```bash
SAT_SIM_DATA_DIR=runtime-data/gpu uv run uvicorn sat_simulation.services.gpu:app --port 8002
SAT_SIM_DATA_DIR=runtime-data/ground SAT_SIM_PLATFORM_UPLINK_HOST=127.0.0.1 SAT_SIM_PLATFORM_HTTP_URL=http://127.0.0.1:8001 uv run uvicorn sat_simulation.services.ground:app --port 8000
SAT_SIM_DATA_DIR=runtime-data/platform SAT_SIM_GROUND_DOWNLINK_HOST=127.0.0.1 SAT_SIM_GPU_GTX_HOST=127.0.0.1 uv run uvicorn sat_simulation.services.platform:app --port 8001
cd web && pnpm dev
```

命令行闭环：

```bash
uv run python scripts/demo_mission.py
```

## 主要公共 API

- `POST /api/scenes/import`：导入并预置 16-bit GeoTIFF。
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
- `sat_simulation/optical`：确定性场景与 RAW/L0/L1A/L1B/STAC。
- `sat_simulation/payload`：检测与语言 Provider 契约。
- `sat_simulation/services`：ground、platform、GPU 三个进程。
- `web`：Next.js/Cesium 地面站。
- `migrations`：PostgreSQL/SQLite Alembic 迁移。
- `scenarios`：版本化演示参数。
- `docs`：架构、协议 ICD、产品定义和运行手册。

## 明确未实现

- 红外载荷仅返回 `not_implemented`。
- 未配置 YOLO/LLM 时第五步为 `blocked`；配置后可原阶段重试。
- 不包含完整传感器物理、GTX 电气特性、RF 物理层、安全加固或 CCSDS 认证。

详见 [架构](docs/ARCHITECTURE.md)、[协议 ICD](docs/PROTOCOL.md)、
[光学产品](docs/PRODUCTS.md) 和 [运行手册](docs/OPERATIONS.md)。
