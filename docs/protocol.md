# Protocol overview

Normal DMX universes use packed canonical fragment headers. Receivers enforce
magic, version, packet type, universe, fragment geometry, coverage, sequence
ordering, and complete promotion.

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
telemetry sequence, and Feature 13 fail-safe mode, active state, timeout,
configuration generation, and activation count.