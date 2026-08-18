# Architecture

The V1 runs four isolated nodes plus a web client and SQLite/PostgreSQL persistence:

```text
web -> ground-api --COMMAND/RESULT_REQUEST uplink TCP--> platform-node
                    ^                                      |       |
                    |                         Payload Bus   |       | GTX L0+aux
                    |                                      v       v
                    |                                 optical    gpu/Jetson
                    |                                  RAW/L0      L1/AI
                    +--------- RESULT_PACKAGE downlink <--- platform
```

Only `ground-api` is public. Scenario control is an out-of-band SIL management
plane; mission commands and all flight products use the simulated links. Each
node has a different volume. A read-only or staged scene is environmental sensor
input, not a spacecraft product.

The ground node owns the authoritative run ID, frozen three-window SGP4 plan and
simulation clock. A mission persists the macro phase
`initialized -> uplink_complete -> capture_complete -> processing_complete ->
gtx_complete -> ai_complete -> completed`. Each advance runs exactly one phase,
records an attempt and ends with both Ground and Platform clocks paused.

Optical owns the selected scene input and generates RAW and L0. Platform receives
both only through the framed Payload Bus. Platform packages L0 plus frozen orbit,
attitude, georeference and calibration context into `L1_JOB`; GPU/Jetson produces
L1A/L1B/STAC and returns `L1_PRODUCTS` over GTX. AI consumes only the verified L1B.
The final ground result
package contains AI JSON, L1B, summary, manifests, STAC and thumbnail; it is created
only after a mission-ID result request in the next Beijing pass.

Built-in processors run in their owning node. Customer ZIP processors run only in
a network-disabled, non-root OCI container with a read-only root filesystem and
bounded CPU, memory, PIDs, time and output space. There is no host-Python fallback.

The software intentionally does not model GTX PHY, SerDes, PCB signal integrity,
RF modulation, or CCSDS conformance.
