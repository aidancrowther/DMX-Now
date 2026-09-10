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