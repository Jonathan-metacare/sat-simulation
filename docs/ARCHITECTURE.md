# 桌面 App 架构

桌面 App 在本机运行 Ground、Platform、Optical、内嵌界面与 SQLite 持久化；`web`
仅指 Electron 内嵌的渲染层。项目只交付完整 App，不提供独立前端、后端或浏览器 Web
服务部署。L1/AI 可由 App 内嵌 GPU Payload 执行，或迁移到受信任 LAN 上的 Jetson：

```text
web -> ground-api --COMMAND/RESULT_REQUEST uplink TCP--> platform-node
                    ^                                      |       |
                    |                         Payload Bus   |       | GTX L0+aux
                    |                                      v       v
                    |                                 optical    gpu/Jetson
                    |                                  RAW/L0      L1/AI
                    +--------- RESULT_PACKAGE downlink <--- platform
```

Ground 是 App 内部唯一的 UI API；场景控制是带外 SIL 管理平面，任务命令与飞行产品
均走模拟链路。每个节点有独立的本地数据目录。只读或暂存场景属于环境传感器输入，
不是航天器产品。

The ground node owns the authoritative run ID, frozen three-window SGP4 plan and
simulation clock. A mission persists the macro phase
`initialized -> uplink_complete -> capture_complete -> processing_complete ->
gtx_complete -> ai_complete -> completed`. Each advance runs exactly one phase,
records an attempt and ends with both Ground and OBC clocks paused.

Optical owns the selected scene input and generates RAW and L0. OBC receives
both only through the framed Payload Bus. OBC packages L0 plus frozen orbit,
attitude, georeference and calibration context into `L1_JOB`; GPU/Jetson produces
L1A/L1B/STAC and returns `L1_PRODUCTS` over GTX. In Jetson GPU mode this is the
remote L1 processing boundary; AI consumes only the verified L1B.
The final ground result
package contains AI JSON, L1B, summary, manifests, STAC and thumbnail; it is created
only after a mission-ID result request in the next Beijing pass.

Built-in processors run in their owning node. On the desktop, custom ZIP processors
use the application-managed Seatbelt runner. On Jetson, custom L1 processors use a
network-disabled, non-root OCI container with a read-only root filesystem and bounded
CPU, memory, PIDs, time and output space. There is no host-Python fallback.

The software intentionally does not model GTX PHY, SerDes, PCB signal integrity,
RF modulation, or CCSDS conformance.
