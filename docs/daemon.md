# Host daemon

Install and run:

```bash
cd wireless_dmx_daemon
python3 -m pip install .
wireless-dmx run --config config.example.toml
```

Configuration sections cover the transmitter serial device, Linux PTY,
Art-Net, source arbitration, pacing, telemetry, priority traffic, channel
gates, and receiver fail-safe behavior. See `config.example.toml` for all
fields.

The daemon clears the transmitter receiver cache on startup, reconnects a lost
transmitter, rejects stale telemetry, and reapplies runtime receiver fail-safe
configuration after startup, receiver discovery, transmitter reconnect, or
receiver reboot.

The dashboard displays daemon health, input/pacer statistics, receiver link and
fail-safe state, priority state, and events. Its setup editor includes fail-safe
mode and timeout.