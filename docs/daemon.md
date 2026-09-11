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

## Dashboard hotkeys

### Main view

| Key | Action |
|---|---|
| `d` | Start or stop the daemon. |
| `r` | Request immediate telemetry. |
| `s` | Open configuration. |
| `u` | Open the manual universe editor. |
| `x` | Open advanced hardware testing. |
| `l` | Show or hide the event log. |
| `q` | Stop components and quit. |

### Configuration editor

| Key | Action |
|---|---|
| Up/Down or `j`/`k` | Select a setting. |
| `e` | Edit the selected setting. |
| `w` | Save atomically. |
| `x` | Discard changes and return. |
| `q` | Quit. |

### Manual universe editor

| Key | Action |
|---|---|
| Up/Down or `j`/`k` | Select a channel; move by rows in grid mode. |
| Left/Right | Move one channel in grid mode. |
| `a` | Jump to a channel. |
| `e` | Set a channel value. |
| `+`/`-` | Nudge a channel value. |
| `l` | Cycle the selected channel gate. |
| `n`/`p` | Select normal or priority transmission. |
| `r` | Cycle priority repeat count. |
| `t` | Cycle priority TTL. |
| Enter | Send the complete current universe. |
| `c` | Clear editable channels. |
| `z` | Reset editable channels to zero without transmitting. |
| `u` | Toggle full-universe view. |
| `g` | Toggle grid view. |
| `x` | Return to the main dashboard. |
| `q` | Quit. |

Priority sends report the priority ID, expected receivers, acknowledged
receivers, retry count, and gate-applied receivers when applicable.

### Advanced hardware view

| Key | Action |
|---|---|
| `m` | Connect to the configured monitor and start a bounded measurement. |
| `a` | Launch the external acceptance runner. |
| `b` | Abort the active monitor measurement. |
| `x` | Return to the main dashboard. |
| `q` | Quit. |