# Architecture

The V1 runs three isolated nodes plus a web client and PostgreSQL:

```text
web -> ground-api --COMMAND/RESULT_REQUEST uplink TCP--> platform-node
                    ^                                   |       ^
                    |                         AI_JOB/EXECUTE     | AI_RESULT
                    |                                   v       |
                    +---- RESULT_PACKAGE downlink -----+  gpu-node
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

RAW/L0/L1A/L1B remain on Platform. Only L1B crosses GTX. The final ground result
package contains AI JSON, summary, manifests, STAC and thumbnail; it is created
only after a mission-ID result request in the next Beijing pass.

The software intentionally does not model GTX PHY, SerDes, PCB signal integrity,
RF modulation, or CCSDS conformance.
