# 数据库与本地数据维护

本项目的 Ground 服务使用 SQLite 保存任务编排、事件、产品目录和处理器版本；大文件
则保存在各节点自己的数据目录。数据库中的 `artifact_path` 只是文件索引，删除 SQLite
记录不会自动删除 RAW、L0、L1 或 AI 结果文件。

> **先完全退出 SpaceZenith-Sim / `pnpm desktop:dev`，或停止 Ground、Platform、Optical、GPU
> 四个服务，再执行本文中的维护操作。** 否则 SQLite 可能被锁定，而且正在运行的任务会
> 被中断并留下不一致的节点本地文件。

## 数据目录

| 运行方式 | SQLite 数据库 | 节点文件与设置 |
| --- | --- | --- |
| 已安装 macOS 桌面版 | `~/Library/Application Support/SpaceZenith-Sim/runtime-data/sat-simulation.db` | 同一 `runtime-data/` 下的 `ground/`、`platform/`、`optical/`、`gpu/`；桌面设置为 `~/Library/Application Support/SpaceZenith-Sim/desktop-settings.json` |
| `pnpm desktop:dev` | 通常为 `~/Library/Application Support/Electron/runtime-data/sat-simulation.db` | 同一 Electron 用户数据目录；开发版窗口标题仍可为 SpaceZenith-Sim |

先确认目标文件确实存在：

```bash
DB="$HOME/Library/Application Support/SpaceZenith-Sim/runtime-data/sat-simulation.db"
sqlite3 "$DB" ".tables"
```

维护前建议备份：

```bash
mkdir -p "$HOME/Library/Application Support/SpaceZenith-Sim/backups"
cp "$DB" "$HOME/Library/Application Support/SpaceZenith-Sim/backups/sat-simulation-$(date +%Y%m%d-%H%M%S).db"
```

## SQLite 表与用途

| 表 | 内容 | 清理任务时是否删除 |
| --- | --- | --- |
| `simulation_scenarios` | 场景配置、当前仿真时钟、当前 L0/L1 处理器选择 | 否；保留以继续使用场景 |
| `simulation_missions` | Mission 命令、冻结的场景/处理器快照、阶段和执行状态 | 是 |
| `simulation_mission_step_attempts` | 每次单步的幂等键、阶段、成功/失败记录 | 是 |
| `simulation_events` | 遥测、状态机、链路和节点事件 | 是，按 `mission_id` 删除 |
| `simulation_products` | RAW/L0/L1A/L1B/STAC/缩略图/AI 结果的产品目录和文件路径 | 是 |
| `simulation_transfers` | 数传、Payload Bus、GTX 传输汇总 | 是 |
| `simulation_protocol_transactions` | 协议事务摘要、JSON 正文/二进制摘要 | 是 |
| `simulation_protocol_frames` | 协议帧头、CRC、重传和 ACK/NAK 轨迹 | 是，必须先于事务表删除 |
| `simulation_faults` | 场景故障注入规则 | 视需要；默认保留 |
| `simulation_scenes` | 已导入的光学场景资产元数据、SHA-256、路径 | 否；删除后场景不能再使用对应 GeoTIFF |
| `simulation_processor_versions` | 自定义 L0/L1 处理器版本、ZIP SHA、资源限制与源信息 | 视需要；删除前应先将场景切回 Built-in |
| `simulation_processor_executions` | L0/L1 安全执行器的资源、stdout/stderr 摘要与失败原因 | 是，按 `mission_id` 删除 |

内置 `builtin-l0`、`builtin-l1` 不是数据库版本记录。它们会在 Optical/GPU 服务启动时
重新生成，因此可以安全地将场景切回这两个默认 ID。

## 清理单个任务及其 L0/L1 产品

先设定要删除的任务 ID，并可先查看相关记录：

```bash
MISSION_ID="mission_xxx"
sqlite3 "$DB" "SELECT id, name, phase, execution_state FROM simulation_missions WHERE id = '$MISSION_ID';"
```

确认 ID 无误后，执行以下事务。它保留场景、场景资产和当前处理器选择：

```bash
sqlite3 "$DB" <<SQL
BEGIN IMMEDIATE;
DELETE FROM simulation_protocol_frames
 WHERE transaction_id IN (
   SELECT id FROM simulation_protocol_transactions WHERE mission_id = '$MISSION_ID'
 );
DELETE FROM simulation_protocol_transactions WHERE mission_id = '$MISSION_ID';
DELETE FROM simulation_transfers WHERE mission_id = '$MISSION_ID';
DELETE FROM simulation_products WHERE mission_id = '$MISSION_ID';
DELETE FROM simulation_processor_executions WHERE mission_id = '$MISSION_ID';
DELETE FROM simulation_mission_step_attempts WHERE mission_id = '$MISSION_ID';
DELETE FROM simulation_events WHERE mission_id = '$MISSION_ID';
DELETE FROM simulation_missions WHERE id = '$MISSION_ID';
COMMIT;
SQL
```

随后清理各节点相同 Mission ID 的文件目录。先列出，再只删除完全匹配的目录：

```bash
ROOT="$HOME/Library/Application Support/SpaceZenith-Sim/runtime-data" # desktop:dev 时改为 .../Electron/runtime-data
find "$ROOT" -type d -name "$MISSION_ID" -print
```

确认输出仅为该任务的目录后，逐一删除这些明确列出的目录；典型位置为：

```text
ground/artifacts/<MISSION_ID>/
platform/products/<MISSION_ID>/
optical/products/<MISSION_ID>/
gpu/jobs/<MISSION_ID>/
```

重新启动应用后，任务列表中不应再出现该任务。

## 清空全部任务历史，保留场景与处理器选择

这会删除所有 Mission、事件、产品目录索引、协议记录和执行记录；不会删除场景、导入的
GeoTIFF、YAML 配置、处理器版本或桌面设置。

```bash
sqlite3 "$DB" <<'SQL'
BEGIN IMMEDIATE;
DELETE FROM simulation_protocol_frames;
DELETE FROM simulation_protocol_transactions;
DELETE FROM simulation_transfers;
DELETE FROM simulation_products;
DELETE FROM simulation_processor_executions;
DELETE FROM simulation_mission_step_attempts;
DELETE FROM simulation_events WHERE mission_id IS NOT NULL;
DELETE FROM simulation_missions;
COMMIT;
VACUUM;
SQL
```

再按上一节列出并删除 `ground/artifacts/`、`platform/products/`、
`optical/products/`、`gpu/jobs/` 下的每个 `mission_*` 目录。不要删除 `scenes/` 或
`processors/`，否则会连同导入的 GeoTIFF 或自定义处理器 ZIP 一并移除。

## 将 L0/L1 处理器选择恢复为 Built-in

场景的当前选择保存在 `simulation_scenarios.config_json`。这只影响**后续新建任务**；
已创建任务已经冻结其处理器版本。

恢复全部场景：

```bash
sqlite3 "$DB" <<'SQL'
UPDATE simulation_scenarios
SET config_json = json_set(
  config_json,
  '$.l0_processor_id', 'builtin-l0',
  '$.l1_processor_id', 'builtin-l1'
);
SQL
```

只恢复一个场景时，附加 `WHERE id = 'scenario_xxx'`。验证：

```bash
sqlite3 "$DB" \
  "SELECT id, json_extract(config_json, '$.l0_processor_id'), json_extract(config_json, '$.l1_processor_id') FROM simulation_scenarios;"
```

如果不再需要所有已导入的自定义处理器，可在完成上述恢复、并清空相关任务历史后删除：

```sql
DELETE FROM simulation_processor_versions;
```

同时删除 Ground、Optical、GPU 三个 `processors/` 目录中的自定义 ZIP。Optical 的
`builtin-l0.zip` 与 GPU 的 `builtin-l1.zip` 可保留（服务启动时也会重新创建它们）。

## 完全恢复为首次启动状态

这是最后手段：删除 SQLite、所有节点运行数据、导入场景和自定义处理器。保留
`desktop-settings.json` 可保留语言、主题、Cesium Token 和 AI Provider；删除它则连这些
本机设置也会重置。

1. 退出应用。
2. 备份整个 `runtime-data/` 目录。
3. 删除该目录中的 `sat-simulation.db`、`ground/`、`platform/`、`optical/`、`gpu/`。
4. 重启应用；Ground 会重新创建默认北京场景和空数据库。

如果还要让桌面版回到默认主题、语言、场景和 Provider 配置，再单独删除
`desktop-settings.json` 后重启。
