# Firmware

This directory contains the production ESP8266 firmware roles for DMX Now.

## Roles

- `Receiver/` — receives QuickESPNow fragments and regenerates physical DMX512.
- `Transmitter/` — host-connected integrated transmitter with ENTTEC input,
  telemetry, management, priority traffic, and optional management-only
  observed-universe support.
- `ReTransmitter/` — receives physical DMX through a receive-only RS-485 input
  and rebroadcasts the normal three-fragment wireless protocol.

The native/integrated transmitter production target is 20 Hz. The standalone
physical-DMX retransmitter production target is 10 Hz.

Build and flash from the repository root with the helpers in `../Helpers/`:

```bash
./Helpers/flash_receiver.sh
./Helpers/flash_transmitter.sh
./Helpers/flash_retransmitter.sh
```

Compilation is the default. Add `-f --port <device>` only after confirming the
target board and serial adapter. Diagnostic and fault-injection images are not
production images and must be replaced before fixture use.