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