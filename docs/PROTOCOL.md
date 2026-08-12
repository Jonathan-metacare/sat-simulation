# SIMF protocol ICD v1

`SIMF` is the shared binary envelope used over TCP. Numeric values use network
byte order. The fixed header carries magic, protocol version, link code, message
type, transfer/run/mission UUIDs, sequence, total frame count, payload length,
simulation timestamp in nanoseconds, and CRC32C. Payloads are split according to
the link profile. EOF prompts ACK or a NAK list; missing or CRC-failed frames are
selectively retransmitted. Completed products also require SHA-256 agreement.

Application message types are `COMMAND`, `AI_JOB`, `AI_EXECUTE`, `AI_RESULT`,
`RESULT_REQUEST`, `RESULT_PACKAGE`, control, event and product. Transport control
uses EOF, ACK and NAK. `AI_RESULT` uses a separate GPU-to-Platform GTX listener;
it is never hidden inside the `AI_EXECUTE` ACK.

The space-ground behavior is a CCSDS-aligned subset: command/telemetry payloads
have Space Packet semantics, transfer frames have TC/AOS-style sequencing, and
file transactions use CFDP-style metadata/data/EOF/ACK/NAK/resume behavior. This
project does not claim standards conformance.

Fault rules are applied with a scenario seed and support drop, corruption,
duplication, reordering, disconnection and added latency. Queue capacity and
bandwidth are enforced before and during transfer.
