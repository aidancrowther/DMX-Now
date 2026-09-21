# Build and flash helpers

The scripts in this directory compile or flash firmware and hardware test
sketches using `arduino-cli`. They are intended to be run from the repository
root, although each script derives its own absolute project root.

## Production firmware

```bash
./Helpers/flash_transmitter.sh
./Helpers/flash_receiver.sh
./Helpers/flash_retransmitter.sh
```

Helpers compile by default. Add `-f --port <device>` to flash a selected board.
The transmitter helper supports `--management-only`, `--lock-management-only`,
`--lock-bridge`, and `--d1`. The retransmitter helper supports `--production`,
`--telemetry-only`, `--d1`, channel, universe, rate, menu configuration, and extra
compiler definitions. Production retransmitter builds include telemetry; the
telemetry-only option is for scheduler/control testing and disables DMX input and
normal retransmission.

## Bench and diagnostic sketches

The remaining helpers target the sketches under `../Tests/`, including ESP-NOW
checks, Mega DMX controllers/monitors, the Pico monitor, GPIO diagnostics, and
the retransmitter end-to-end Mega harness. Refer to `../Docs/testing.md` before
running a hardware test.

Diagnostic and fault-injection builds are compile/test images. Always restore a
production image after testing and confirm the target serial port before using
`-f`.