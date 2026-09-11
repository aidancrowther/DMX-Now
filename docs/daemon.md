# Host daemon

Install and run:

```bash
cd wireless_dmx_daemon
python3 -m pip install .
wireless-dmx run --config config.example.toml
```

configuration sections cover the transmitter serial device, ENTTEC and raw-DMX
Linux PTYs, Art-Net, source arbitration, pacing, telemetry, priority traffic, channel
gates, and receiver fail-safe behavior. See `configs/config.example.toml` for all
fields.

The daemon clears the transmitter receiver cache on startup, reconnects a lost
transmitter, rejects stale telemetry, and reapplies runtime receiver fail-safe
configuration after startup, receiver discovery, transmitter reconnect, or
receiver reboot.

The optional `[raw_virtual_port]` creates a second Linux PTY for raw DMX input.
Write exactly one 512-byte DMX universe per burst; the parser also tolerates
partial OS reads and concatenated bursts. Select it exclusively with
`[input] source_policy = "raw_serial"`, or use `latest` to arbitrate it with
the other enabled inputs. The printed raw-DMX PTY path is separate from the
ENTTEC-compatible PTY.
`timeout_seconds` defaults to 1.0 and abandons an incomplete universe after
that interval without changing the previously active universe.
Because raw DMX has no delimiter or length marker, the raw input stream must
remain aligned to 512-byte universe boundaries; an extra or missing byte cannot
be resynchronized automatically.

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
| `n` | Open the persistent receiver-name editor. |
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

When the dashboard is started without `--config`, it opens a configuration-file
selector before starting the daemon. Choose a `.conf` or `.toml` file with
Up/Down or `j`/`k` and press Enter. Press `c` on the main dashboard to reopen
the selector; selecting another file stops the current daemon before loading
the new configuration. Supplying `--config <path>` skips the selector and is
still supported for CLI and scripted management.

The selector searches `wireless_dmx_daemon/configs/`. The checked-in
`default.conf` and `config.example.toml` files are read-only baselines. In the setup editor,
press `a` for Save As, enter a new `.toml` or `.conf` filename, and press Enter.
The new file is saved atomically and becomes the active dashboard configuration.
Use `w` to save subsequent edits to that active file. Save As cannot overwrite
`default.conf` or `config.example.toml`.

After a writable configuration is selected or saved, it is remembered for the
next dashboard launch. If no remembered writable file exists, the newest
writable configuration in `configs/` is selected automatically; otherwise the
selector opens with the read-only default baseline selected.

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

In full-universe grid mode, type a DMX value directly with the number keys. The
typed value appears in the selected cell; press Enter to apply it. Values from
0 through 255 are accepted. Backspace removes the last digit, and navigation
clears an unfinished entry. Pressing Enter without a typed value retains the
existing behavior of sending the complete manual universe.

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

The receiver-name editor lists discovered receivers, including stale/offline
receivers retained in the telemetry cache. Select a receiver with Up/Down or
`j`/`k`, press `e`, enter a friendly name, and press Enter. Names are saved
atomically to the active TOML file under `[receiver_names]`; submitting a blank
name removes the alias. The dashboard continues to show the stable `RX-...`
hardware ID beside each name.

The compact receiver table displays up to 16 name characters beside the stable
hardware ID. Longer names scroll slowly within that fixed-width field so they do
not overlap link, battery, RSSI, or counter columns. The name editor and
receiver-selection modals display the full configured name.

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