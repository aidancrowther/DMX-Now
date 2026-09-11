# Testing guide

Host validation:

```bash
cd wireless_dmx_daemon
python3 -m pytest -q
python3 -m py_compile wireless_dmx/**/*.py tests/*.py
```

Firmware validation:

```bash
./helpers/flash_receiver.sh
./helpers/flash_transmitter.sh
```

To isolate ESP-01/ESP-01S onboard LED and pin wiring from the production
receiver, use the standalone GPIO diagnostic:

```bash
./helpers/flash_gpio_blink.sh
./helpers/flash_gpio_blink.sh -f --port /dev/ttyUSB0
```

This test does not initialize DMX, Wi-Fi, or QuickESPNow. It drives GPIO1 and
GPIO2 together with a 500 ms half-period (one full blink per second).

The integrated receiver locator uses the same GPIO pins for a 15-second default
interval. It is disruptive to DMX output and should only be used with the
receiver disconnected from DMX fixtures.

Hardware tests should discover receiver IDs dynamically and never assume which
receiver is connected to a physical monitor. Use finite Mega monitor commands;
`disable_line` intentionally produces no DMX data and must not cause an
unbounded wait.

Recommended coverage includes normal output, priority/gates, receiver removal
and recovery, transmitter reset, daemon restart, PTY reconnect, and all three
fail-safe modes. For blackout/disable-line testing, establish a normal baseline
before stopping wireless fragments. The test-only transmitter define
`-DTEST_SUPPRESS_DMX_TRANSMISSION` suppresses DMX fragments while preserving
management/telemetry; restore the production transmitter image afterward.

## Raw DMX timeout validation with the Mega monitor

The raw-DMX path can be validated with the existing Arduino Mega DMX monitor
without changing receiver firmware:

1. Build a writable configuration with `[raw_virtual_port] enabled = true`,
   `source_policy = "raw_serial"`, and `timeout_seconds = 1.0`.
2. Start the daemon with that configuration and record the printed raw-DMX PTY.
3. Connect the Mega monitor to the receiver DMX output and establish a baseline
   using a complete constant universe, for example all channels set to `77`.
4. Write a different universe value, such as `99`, to the raw PTY in two parts,
   but stop before 512 bytes are sent.
5. Wait at least 1.2 seconds. The daemon's `raw_serial_timeout_drops` counter
   should increase, and the receiver should continue holding the previous
   complete universe.
6. Send one complete 512-byte universe of `99` and verify that the Mega records
   valid DMX frames with the new value and no mixed or partial universe.
7. Repeat with partial lengths near the boundary (1, 255, 511 bytes), with a
   pause below the timeout to confirm completion still works, and with a pause
   above the timeout to confirm abandonment.
8. Repeat at the intended operating cadence (for example 20 complete bursts per
   second) for a finite 60-second run. Require positive Mega checks, zero
   pattern/content failures, no unexplained no-data gaps, and zero unexpected
   timeout drops during complete-burst operation.

The Mega monitor's `START` command must always use a finite measurement window;
do not wait indefinitely for `disable_line` or a deliberately absent raw burst.
This procedure validates both raw input framing and end-to-end physical DMX
output. The timeout itself is validated by the absence of a partial promotion
and successful recovery on the next complete universe.