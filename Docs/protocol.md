# Protocol overview

Normal DMX universes use packed canonical fragment headers. Receivers enforce
magic, version, packet type, universe, fragment geometry, coverage, sequence
ordering, and complete promotion.

In a retransmitter deployment, normal `DMX_PACKET_TYPE` fragments have exactly
one authority: the physical-DMX re-transmitter. A management-only transmitter
must not emit normal fragments. It may emit `DMX_PRIORITY_PACKET_TYPE` and
matching gate metadata for explicit management operations; those packets are a
separate receiver reconstruction path.

Priority fragments add target receiver, priority ID, attempt, and repeat count.
Priority gate metadata is staged independently and applied only when the
matching complete priority universe is reconstructed. Completion ACKs identify
ordinary acceptance, duplicate/invalid states, and gate application.

Management frames use:

```text
A5 5A | version | opcode | little-endian length | payload | CRC-16/CCITT
```

Telemetry reports are multipart bounded records. They include identity, battery,
RSSI, uptime, sequence/counters, last-universe age, firmware/protocol versions,
telemetry sequence, and receiver fail-safe mode, active state, timeout,
configuration generation, and activation count.

## Optional management-only universe observation

Management-only transmitters may passively reconstruct ordinary `DMX_PACKET_TYPE`
fragments heard from the standalone physical-DMX retransmitter. This does not use
Wi-Fi promiscuous mode and does not make the management transmitter a normal-DMX
authority. A bounded callback handoff reconstructs complete universes in the main
loop; incomplete or malformed observations are discarded.

The host requests the latest snapshot with management opcode `0x0A`. The
transmitter returns three CRC-protected `0x8A` multipart responses. Each part
contains the observation sequence, age, source MAC, channel offset, and channel
bytes. The daemon promotes the snapshot atomically only after all parts match.

This is an optional best-effort operator display feature. The daemon polls at a
low rate in management-only mode and keeps observation state separate from the
editable/manual universe and the DMX pacer. Locally transmitted priority values
provide the display fallback because an ESP-NOW transmitter cannot receive its
own broadcast. A complete retransmitter observation supersedes that fallback;
daemon `LOCKED` channels remain at their local values to match receiver hard-gate
behavior. Observation loss never stops normal receiver output or management
traffic.