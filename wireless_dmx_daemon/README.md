# DMX Now Host Daemon

This directory contains the host-side bridge for the DMX Now ESP8266 system
system. The daemon will expose a virtual ENTTEC-compatible serial port to
lighting software, forward validated DMX data to the ESP8266 transmitter at
115200 8N2, pace DMX frames at the validated 20 Hz wireless rate, and expose
receiver telemetry and operating statistics through a CLI and future GUI/API.

## Project attribution

This host software is vibe coded with AI assistance. The underlying Wireless
DMX hardware was designed by me.

## Initial assumptions

* Initial host platform: Linux.
* Initial virtual serial implementation: Linux PTYs for ENTTEC-compatible and
  optional raw-DMX input, isolated behind replaceable backend adapters.
* Transmitter connection: configurable serial device, default `/dev/ttyUSB0`.
* Transmitter serial format: 115200 baud, 8 data bits, no parity, 2 stop bits.
* Default wireless pacing rate: 20 Hz.
* Art-Net ArtDMX input is enabled by default on UDP port 6454, Universe 0.
* ENTTEC serial, raw-DMX serial, and Art-Net inputs can be enabled independently
  or together.
* Rates above 20 Hz require an explicit experimental override.
* Telemetry is binary management traffic. The transmitter's text
  telemetry logging is not enabled during normal operation because it would
  corrupt the shared ENTTEC/management UART.

## Architecture

```text
CLI / future GUI
        |
Application service and state snapshots
        |
  +-----+----------+----------------+
  |                |                |
PTY backend    ENTTEC parser    Telemetry store
  |                |                |
  +----------> DMX pacer <-------+
                    |
           Transmitter connection
                    |
             ESP8266 transmitter
```

Core code must not depend directly on terminal presentation, operating-system
PTY details, or a particular serial library. Those concerns belong in adapter
modules.

## Phased implementation plan

### Protocol and architecture contract

Create the package structure, core dataclasses, configuration model, protocol
contracts, and service-state snapshots. Add dependency-free tests for these
interfaces. No live serial or OS-specific behavior is required.

**Completion criteria:** package imports cleanly; public interfaces are
documented; models are immutable where appropriate; unit tests cover defaults,
validation, receiver state calculation, and statistics; future CLI/GUI code can
consume a service snapshot without accessing I/O objects.

### ENTTEC protocol parser and statistics

Implement a streaming parser supporting partial reads, concatenated frames,
embedded delimiter bytes, valid short/full universes, malformed lengths,
unsupported labels, and recovery after corruption. Track input and rejection
statistics.

**Completion criteria:** parser cases pass as host tests;
valid frames produce one normalized DMX universe; malformed input cannot alter
the active universe.

### Transmitter serial connection

Implement configurable 115200 8N2 serial I/O, bounded read/write behavior,
reconnection, timeouts, clean shutdown, and a fake serial adapter for tests.

**Completion criteria:** `/dev/ttyUSB0` can be opened with the correct format;
serial failure recovery is tested without hardware; no unbounded write queue
exists.

### DMX pacer

Implement latest-state pacing. New input replaces an unsent pending frame;
obsolete frames are counted as dropped rather than queued. Make target rate,
limits, policy, and experimental override configurable.

**Completion criteria:** a 40 Hz input stream produces approximately 20 Hz
transmitter submissions by default; pacer statistics distinguish received,
submitted, and dropped frames.

### Virtual serial port

Implement the Linux PTY backend. Expose the slave path, optionally create a
safe configurable symlink, tolerate no client/client reconnect, and clean up on
shutdown. Keep OS-specific details behind a backend interface.

**Completion criteria:** a normal serial application can open the virtual port;
ENTTEC bytes reach the parser; client disconnects do not crash the daemon.

### Binary telemetry management

Implement telemetry requests, CRC validation, multipart report grouping,
receiver storage, freshness states, retries, and background scheduling.

**Completion criteria:** one and multiple receivers are decoded; multipart
responses work; malformed/old reports are rejected; telemetry never blocks DMX
pacing.

### CLI interface

Add `run`, `status`, `receivers`, `stats`, `config-check`, and `version`
commands. The CLI renders service snapshots rather than owning business logic.

**Completion criteria:** current DMX and receiver state is visible; startup and
shutdown are clean; a future GUI can reuse the service layer.

### Configuration and persistence

Add TOML configuration, command-line overrides, validation, effective-config
display, and safe defaults.

**Completion criteria:** invalid device/rate/timeout settings fail before I/O;
CLI overrides take precedence over file values.

### Resilience and service operation

Add transmitter reconnect, PTY client reconnect, bounded backoff, signal
handling, health states, structured logs, and optional systemd integration.

**Completion criteria:** transmitter unplug/replug and daemon restart recover
without replaying stale DMX history.

### Hardware validation

Run the daemon with the real transmitter and Arduino Mega monitor. Validate
20 Hz operation, telemetry, malformed input recovery, receiver disappearance,
transmitter reset, and virtual-port reconnect behavior.

**Completion criteria:** more than ten minutes at 20 Hz with zero Mega DMX
pattern failures, no unexplained no-data gaps, valid telemetry, bounded memory,
and safe reconnect behavior.

## Current implementation status

The host status/management scope is complete for the validated Linux/20 Hz
deployment. The package has
standard-library core models, a streaming ENTTEC parser, binary management
codec, bounded latest-state pacer, reconnecting transmitter adapter, Linux PTY
backend, TOML loading, CLI entry point, structured logging, and a systemd unit
template. Reliability/throughput testing, hardware fail-safe refinement,
targeted priority transmission, and receiver hard gating are **COMPLETE for the
validated Linux/20 Hz hardware
configuration**: manual complete-universe sends,
bounded queueing, repeat/TTL handling, receiver ACKs, per-receiver
retry/recovery, lead-in/lead-out timing, receiver-side runtime hard locks, and
normal-stream resumption are implemented. The detailed priority completion
record is
`../docs/priority-packet-substantial-completion.md`.
The current hardware qualification covers dynamic receiver discovery, hard-gate
establishment/unlock, normal-packet blocking, normal resumption, receiver
removal/reconnection, transmitter reset recovery, daemon restart recovery, PTY
client disconnect/reconnection, priority soak, and all three receiver fail-safe
modes. Native Windows/macOS virtual serial support, broader platform/application
coverage, and a future GUI remain follow-up work.

The host implementation has passed the automated suite and live validation. The
live path opens the configured transmitter, exposes a Linux PTY, forwards full
ENTTEC universes, and receives telemetry from dynamically discovered receivers.
The existing ESP8266/Mega 660-second acceptance run remains the authoritative
physical DMX/RF evidence; the host daemon's live test confirms the additional
PTY, parser, pacing, transmitter-serial, and telemetry integration path.

### Reliability, fail-safe, and priority completion evidence

The final lab acceptance completed with 36,000 DMX frames submitted at 20 Hz
and 79,869/79,869 Mega checks passing. Priority events produced no failed,
retried, invalid, or unknown completions.

The hard-gate test passed lock and unlock transactions:

* all expected receivers reported `PRIORITY_COMPLETE_GATE_APPLIED`;
* both transactions succeeded on the first attempt with zero retries;
* normal traffic remained blocked at the locked priority value;
* normal output resumed after the unlock transaction;
* all Mega measurement windows had zero failures.

The priority soak produced 20/20 first-attempt successes, zero
failed events, zero retry recoveries, zero invalid/unknown ACKs, and zero retry
failures. The duplicate ACK records reported by the soak are expected repeated
physical completion records and did not affect event completion.

Hardware intervention coverage also passed: receiver removal/reconnection,
transmitter reset with the daemon running, daemon restart, and PTY client
disconnect/reconnection all recovered with valid normal DMX output. Receiver
fail-safe coverage passed `hold`, `blackout`, and `disable_line` with finite
Mega measurements and automatic recovery. See `../docs/lab-validation.md`.

The default command is:

```bash
python3 -m wireless_dmx run --config configs/config.example.toml
```

Dashboard configuration files live in `configs/`. Starting the dashboard without
`--config` uses the last writable configuration when available, or opens the
interactive configuration selector. The CLI still accepts `--config <path>`.

The printed PTY slave paths are the ports to configure in lighting software. The
daemon owns the physical transmitter at 115200 8N2 and exposes current state
through service snapshots rather than mixing diagnostic text into the ENTTEC
stream.

## Art-Net input

QLC+ can use its Art-Net output plugin to send Universe 0 to the daemon without
requiring a discoverable USB Enttec interface. The default Art-Net listener is:

```text
bind:     0.0.0.0
UDP port: 6454
Universe: 0
```

Configure QLC+ to send Art-Net to the daemon host's IP address and Universe 0.
The daemon normalizes ArtDMX payloads to 512 channels and sends them through the
same 20 Hz latest-state pacer used by the virtual serial input.

An optional second Linux PTY accepts raw DMX universes without ENTTEC framing:

```toml
[raw_virtual_port]
enabled = true
requested_path = "/tmp/wireless-dmx-raw"
timeout_seconds = 1.0

[input]
source_policy = "raw_serial"
```

Write one complete 512-byte universe per burst. The raw-DMX parser handles PTY
partial reads and concatenated bursts while preserving the same source gating
and pacer behavior as other inputs. Incomplete bursts expire after the configured
`timeout_seconds`, which defaults to 1.0 second.

Input combinations are configured in TOML:

```toml
[virtual_port]
enabled = true

[artnet]
enabled = true
bind_host = "0.0.0.0"
port = 6454
universe = 0

[input]
source_policy = "latest" # latest, serial, or artnet
```

Use `source_policy = "serial"` or `"artnet"` to give one input source
exclusive ownership when both are enabled. `latest` accepts whichever valid
source frame arrives most recently.

If no configuration path is supplied, the application loads
`default.conf` from its working directory when present, otherwise it uses the
built-in safe defaults.

The dashboard treats `default.conf` as a read-only baseline. Start the dashboard
without `--config` to choose from available `.conf` and `.toml` files, or press
`c` while it is running to switch configurations. Use Save As in the setup
editor to create a writable configuration file. The `--config` option remains
available for CLI and scripted management.

The Art-Net listener is a UDP input adapter and does not require QLC+ to see a
USB or serial interface. Configure QLC+'s Art-Net output for the daemon host,
Universe 0, and UDP port 6454. The daemon accepts ArtDMX while virtual serial
is enabled, disabled, or used simultaneously. When both sources are enabled,
`input_source_policy = "latest"` accepts the most recent valid frame;
`"serial"` or `"artnet"` can enforce exclusive source ownership.

The end-to-end acceptance runner is intended for a host with a transmitter, a
physical DMX monitor, and the expected receivers online. It submits complete
universes at the configured rate, validates the physical monitor output, and
logs daemon telemetry/progress. Setup-specific evidence is documented in
`../docs/lab-validation.md`.

The end-to-end acceptance runner is:

```bash
python3 tests/run_30min_acceptance.py \
  --tx-port <transmitter-device> \
  --mega-port <monitor-device> \
  --seconds 1800 \
  --run-dir runs/30min-acceptance
```

It opens the daemon PTY as a serial client, streams a complete ramp universe at
20 Hz, validates the physical receiver output with the Arduino Mega, and logs
daemon telemetry/progress. The transmitter's text telemetry logging must remain
disabled because its UART carries the ENTTEC stream.

For a one-shot live receiver query:

```bash
python3 -m wireless_dmx --config config.example.toml status
```

## btop-like management dashboard

The single wrapper application is the curses dashboard:

```bash
python3 wireless_dmx_dashboard.py --config config.example.toml --mega-port <monitor-device>
```

or, after installing the package:

```bash
wireless-dmx-dashboard --config config.example.toml --mega-port <monitor-device>
```

The dashboard owns one in-process `WirelessDmxService`, so it is the preferred
interactive management entry point rather than starting the daemon separately.
It uses a btop-inspired continuously refreshed terminal layout with color-coded
health states, compact ASCII bar visualizations for DMX/pacer activity and RSSI,
and separate panels for daemon state, receiver telemetry, and recent events.

### Dashboard controls

| Key | Action |
|---|---|
| `d` | Start or stop the in-process daemon |
| `r` | Schedule an immediate telemetry request |
| `x` | Enter/leave the Advanced hardware-testing menu |
| `s` | Open the configuration setup editor |
| `l` | Toggle the event panel |
| `q` | Stop components and exit cleanly |

Mega testing and the acceptance runner are intentionally hidden behind the
Advanced menu (`x`) because they are development/validation functions rather
than normal release controls. Inside Advanced:

| Key | Action |
|---|---|
| `m` | Connect to the configured monitor and start a Mega measurement |
| `a` | Launch the external 30-minute acceptance runner |
| `b` | Abort the active Mega measurement |
| `x` | Return to the main dashboard |

The `a` action starts `tests/run_30min_acceptance.py` as a bounded external
process and writes evidence to `runs/dashboard-acceptance/`. The dashboard
does not mix Mega monitor text or diagnostic output into the transmitter UART.
The daemon continues to use binary telemetry management traffic.

The dashboard/controller is separated from curses rendering. Future GUI code
can reuse `DashboardController`, `WirelessDmxService`, `DaemonSnapshot`, and
`MegaMonitorController` without depending on terminal drawing functions.

### Configuration setup editor

Press `s` on the main dashboard to edit the selected configuration fields,
including Art-Net enablement, bind host, UDP port, universe, and input policy.
Navigate with arrow keys or `j`/`k`, press `e` to edit a value, `w` to save
atomically, and `x` to cancel. The editor validates each change before applying
it and saves to the path selected by `--config-path` or the active configuration
path. Restart the daemon after changing settings that affect sockets, PTYs, or
the transmitter connection.

The complete hotkey reference for every dashboard view is in `../docs/daemon.md`
under “Dashboard hotkeys”. It includes manual priority feedback, repeat/TTL
controls, and zero-universe reset.

Manual DMX value entry uses a temporary blocking input mode so typed values are
accepted reliably even though the live dashboard normally uses non-blocking
keyboard polling. In the full-universe manual view, press `g` to switch between
the channel list and a 16-column hex-dump-style grid; the selected channel is
highlighted in either view.

In full-universe grid mode, the left/right arrows move horizontally by one
channel and the up/down arrows move by one 16-channel row. In list and channel
modes, left/right do nothing. Press `a` in any manual mode to jump directly to
channel 1–512.

In grid mode, type a value directly with the number keys and press Enter to
apply it to the selected channel. Values must be 0–255; Backspace removes a
digit. Enter with no typed value continues to send the complete universe.

## Suggested future layout

```text
wireless_dmx_daemon/
├── README.md
├── pyproject.toml                 # introduced with packaging phase
├── wireless_dmx/
│   ├── __init__.py
│   ├── app.py
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── pacer.py
│   ├── stats.py
│   ├── telemetry.py
│   ├── enttec/
│   │   ├── __init__.py
│   │   ├── parser.py
│   │   └── protocol.py
│   ├── transmitter/
│   │   ├── __init__.py
│   │   ├── connection.py
│   │   └── management.py
│   └── virtual_serial/
│       ├── __init__.py
│       ├── base.py
│       └── linux_pty.py
└── tests/
```

## Development rules

* Keep all temporary files inside this project directory.
* Prefer standard-library interfaces in the foundational implementation.
* Keep I/O adapters replaceable and testable with fakes.
* Use fixed/bounded queues and latest-state semantics.
* Do not enable transmitter text telemetry logging while forwarding ENTTEC
  traffic.
* Hardware verification must identify which behaviors were actually measured.