# Architecture

The V1 runs three isolated nodes plus a web client and PostgreSQL:

```text
web -> ground-api --uplink TCP--> platform-node --GTX TCP--> gpu-node
                    ^                 |
                    +--downlink TCP---+
```

Only `ground-api` is public. Scenario control is an out-of-band SIL management
plane; mission commands and all flight products use the simulated links. Each
node has a different volume. A read-only or staged scene is environmental sensor
input, not a spacecraft product.

The ground node owns the authoritative run ID and simulation clock. Platform
timing is controlled through the management plane and every task/link delay uses
`SimulationClock`. Reset creates a new run and keeps previous events.

The software intentionally does not model GTX PHY, SerDes, PCB signal integrity,
RF modulation, or CCSDS conformance.

