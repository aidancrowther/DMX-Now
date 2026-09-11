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
| `o` | Open the centered multi-select receiver menu for MAX3485 output control. |
| `i` | Open the centered multi-select receiver locator. Locating interrupts DMX for 15 seconds. |
| `p` | Open the centered priority-traffic status alert. |
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

The main dashboard's `o` and `i` actions open centered receiver-selection menus.
Use Up/Down or `j`/`k` to move, Space to toggle multiple online receivers, and
Enter to continue. The output menu then accepts `o` for on or `f` for off.
Selecting `ALL ONLINE RECEIVERS` uses the broadcast management packet. Turning
output off is a visible DMX interruption and should be treated as a hardware
test action; the operator must explicitly turn it back on.

The locate menu sends a 15-second request to each selected receiver, or a
single broadcast request for all online receivers. **WARNING: locating disables
DMX and pulses the receiver pins. Use it only when the selected receivers are
disconnected from DMX fixtures.**

Priority universe sends initiated from the manual editor automatically open the
centered priority alert. It remains visible while the transaction is active and
closes 10 seconds after completion with a live countdown; `c` cancels the
automatic close and keeps it open. `x`, `Esc`, or Enter closes it early.
Press `p` on the main dashboard to open the same alert manually. Manually opened
alerts do not use the automatic close timer. The alert repeats
the latest priority ID, status, expected receivers, acknowledged receivers,
retry count, and gate-applied receivers so priority traffic is visible without
relying on the narrow status line.

### Advanced hardware view

| Key | Action |
|---|---|
| `m` | Connect to the configured monitor and start a bounded measurement. |
| `a` | Launch the external acceptance runner. |
| `b` | Abort the active monitor measurement. |
| `x` | Return to the main dashboard. |
| `q` | Quit. |