# Lab validation record

This document records Linux hardware qualifications and is not a required
deployment topology. USB device assignments and monitor wiring are session
specific; receiver identities were discovered from telemetry.

Validated behavior included normal 20 Hz acceptance, priority delivery, hard
gates, receiver removal/reconnection, transmitter reset, daemon restart, PTY
telemetry, priority soak, and receiver `hold`, `blackout`, and
`disable_line` tests.

Fail-safe evidence included a 60-second hold test, a bounded 30-second
blackout test producing a finite all-zero measurement, and a bounded
disable-line test producing zero DMX checks with more than 42 seconds of
no-data. Production transmitter firmware was restored and fresh DMX recovery
passed after each mode.

These results document behavior, not a fixed receiver count, receiver ID set,
USB numbering scheme, or monitor assignment.

## Physical retransmitter qualification

The standalone physical retransmitter has a 10 Hz production target. Its
validated physical-DMX path includes the DMXUART full-frame BREAK correction,
source-frame handling through 512 slots, and receiver-side complete universe
promotion checks. Extended boundary, transition, and long-run testing completed
with matching content and no improper receiver promotion.

The physical retransmitter may be deployed without a management transmitter.
When telemetry/control is required, use a separate transmitter locked to
management-only mode. The management device is optional and must not become a
competing normal-DMX authority. The management-only image also provides an
optional best-effort observed-universe display by listening to retransmitter
fragments and exporting complete snapshots over its host UART. This display is
not yet a substitute for dedicated Firmware/Receiver/DMX measurement and should be
validated separately for radio and UART loss behavior.

For wiring, image roles, flash procedures, port safety, deployment, and both
standalone and monitored deployment procedures, see
[`retransmitter-deployment.md`](retransmitter-deployment.md).