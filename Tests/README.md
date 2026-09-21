# Tests and validation sketches

This directory contains Arduino test sketches, hardware monitors, acceptance
plans, and test-specific harnesses. It is separate from the production firmware
under `../Firmware/` and the automated Python suite under
`../Host Software/wireless_dmx_daemon/tests/`.

## Contents

For the current retransmitter bench, use the
[Pico acceptance mapping](../Docs/pico-retransmitter-testing.md). It replaces
the Mega generator procedure while preserving the test matrix.

- ESP-NOW basic and universe transmitter/receiver checks.
- Mega DMX controllers and physical-DMX monitors.
- Pico refresh monitoring.
- GPIO and receiver diagnostics.
- Retransmitter end-to-end generation and monitoring.
- Feature test plans and the retransmitter acceptance plan.

Use the helpers in `../Helpers/` to compile these sketches. Read
[`../Docs/testing.md`](../Docs/testing.md) and
[`../Docs/lab-validation.md`](../Docs/lab-validation.md) before connecting
hardware. Live runners can open real serial devices and must only be run after
wiring, firmware images, and ports have been explicitly confirmed.
