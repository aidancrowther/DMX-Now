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
not a substitute for dedicated Firmware/Receiver/DMX measurement.

The production retransmitter telemetry/control implementation and extended
validation were completed on the `feature/retransmitter-telemetry-control`
branch (commit `e716a05`). Production operation was accepted at approximately
10 Hz with valid reconstructed content, zero post-sync CRC errors, source
mismatches, sequence backtracks, or wireless send failures. Boundary, transition,
and long-soak runs completed with healthy queues and balanced fragments. The
extended matrix recorded 25/27 passing cases; the two failures were Mega
source-result/reporting checks, not retransmission-integrity failures. Treat
those harness results as reporting follow-up if a fully green extended report is
required.


### Post-reflash locate and DMX smoke evidence

The retransmitter was subsequently restored to the pre-input-gating GPIO
allocation: GPIO2 is the locate indicator, while DMX input remains continuously
available. Locate functionality was verified after flashing. A follow-up 30-second
production smoke test then used the Mega source on `/dev/ttyUSB2`, the diagnostic
receiver on `/dev/ttyUSB1` at 460800 baud, and the management transmitter on
`/dev/ttyUSB0`.

The diagnostic receiver captured 356 valid normal-DMX records with zero CRC or
unknown-record errors. Sequences advanced from 12 through 370 and all records
identified source MAC `cc:50:e3:fd:a9:76`. Retransmitter telemetry increased
input frames from 0 to 253 and wireless frames from 0 to 252, while wireless
send failures remained 0. This confirms physical DMX reception and wireless
retransmission after the locate restoration. Battery-monitor support is available
in production builds through `--battery-monitor`; the smoke test did not assert a
battery level.
For wiring, image roles, flash procedures, port safety, deployment, and both
standalone and monitored deployment procedures, see
[`retransmitter-deployment.md`](retransmitter-deployment.md).