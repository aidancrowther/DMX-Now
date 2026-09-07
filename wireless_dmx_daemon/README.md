# Wireless DMX Host Daemon

This directory contains the host-side bridge for the ESP8266 Wireless DMX
system. The daemon will expose a virtual ENTTEC-compatible serial port to
lighting software, forward validated DMX data to the ESP8266 transmitter at
115200 8N2, pace DMX frames at the validated 20 Hz wireless rate, and expose
receiver telemetry and operating statistics through a CLI and future GUI/API.

## Initial assumptions

* Initial host platform: Linux.
* Initial virtual serial implementation: Linux PTY, isolated behind a backend
  interface for future Windows/macOS VCP implementations.
* Transmitter connection: configurable serial device, default `/dev/ttyUSB0`.
* Transmitter serial format: 115200 baud, 8 data bits, no parity, 2 stop bits.
* Default wireless pacing rate: 20 Hz.
* Rates above 20 Hz require an explicit experimental override.
* Telemetry is binary Feature 11 management traffic. The transmitter's text
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

### Phase 0 — Protocol and architecture contract

Create the package structure, core dataclasses, configuration model, protocol
contracts, and service-state snapshots. Add dependency-free tests for these
interfaces. No live serial or OS-specific behavior is required.

**Completion criteria:** package imports cleanly; public interfaces are
documented; models are immutable where appropriate; unit tests cover defaults,
validation, receiver state calculation, and statistics; future CLI/GUI code can
consume a service snapshot without accessing I/O objects.

### Phase 1 — ENTTEC protocol parser and statistics

Implement a streaming parser supporting partial reads, concatenated frames,
embedded delimiter bytes, valid short/full universes, malformed lengths,
unsupported labels, and recovery after corruption. Track input and rejection
statistics.

**Completion criteria:** existing Feature 8 parser cases pass as host tests;
valid frames produce one normalized DMX universe; malformed input cannot alter
the active universe.

### Phase 2 — Transmitter serial connection

Implement configurable 115200 8N2 serial I/O, bounded read/write behavior,
reconnection, timeouts, clean shutdown, and a fake serial adapter for tests.

**Completion criteria:** `/dev/ttyUSB0` can be opened with the correct format;
serial failure recovery is tested without hardware; no unbounded write queue
exists.

### Phase 3 — DMX pacer

Implement latest-state pacing. New input replaces an unsent pending frame;
obsolete frames are counted as dropped rather than queued. Make target rate,
limits, policy, and experimental override configurable.

**Completion criteria:** a 40 Hz input stream produces approximately 20 Hz
transmitter submissions by default; pacer statistics distinguish received,
submitted, and dropped frames.

### Phase 4 — Virtual serial port

Implement the Linux PTY backend. Expose the slave path, optionally create a
safe configurable symlink, tolerate no client/client reconnect, and clean up on
shutdown. Keep OS-specific details behind a backend interface.

**Completion criteria:** a normal serial application can open the virtual port;
ENTTEC bytes reach the parser; client disconnects do not crash the daemon.

### Phase 5 — Binary telemetry management

Implement Feature 11 requests, CRC validation, multipart report grouping,
receiver storage, freshness states, retries, and background scheduling.

**Completion criteria:** one and multiple receivers are decoded; multipart
responses work; malformed/old reports are rejected; telemetry never blocks DMX
pacing.

### Phase 6 — CLI interface

Add `run`, `status`, `receivers`, `stats`, `config-check`, and `version`
commands. The CLI renders service snapshots rather than owning business logic.

**Completion criteria:** current DMX and receiver state is visible; startup and
shutdown are clean; a future GUI can reuse the service layer.

### Phase 7 — Configuration and persistence

Add TOML configuration, command-line overrides, validation, effective-config
display, and safe defaults.

**Completion criteria:** invalid device/rate/timeout settings fail before I/O;
CLI overrides take precedence over file values.

### Phase 8 — Resilience and service operation

Add transmitter reconnect, PTY client reconnect, bounded backoff, signal
handling, health states, structured logs, and optional systemd integration.

**Completion criteria:** transmitter unplug/replug and daemon restart recover
without replaying stale DMX history.

### Phase 9 — Hardware validation

Run the daemon with the real transmitter and Arduino Mega monitor. Validate
20 Hz operation, telemetry, malformed input recovery, receiver disappearance,
transmitter reset, and virtual-port reconnect behavior.

**Completion criteria:** more than ten minutes at 20 Hz with zero Mega DMX
pattern failures, no unexplained no-data gaps, valid telemetry, bounded memory,
and safe reconnect behavior.

## Current implementation status

Phases 0–8 are implemented in the initial Linux host version. The package has
standard-library core models, a streaming ENTTEC parser, Feature 11 management
codec, bounded latest-state pacer, reconnecting transmitter adapter, Linux PTY
backend, TOML loading, CLI entry point, structured logging, and a systemd unit
template. Phase 9 hardware acceptance still requires running the daemon against
the physical Mega/transmitter combination; the existing ESP8266 firmware and
Feature 11 hardware evidence remain separate from this host component.

The host implementation has passed 21 automated tests and live validation on
2026-09-04. The live test opened the real transmitter at `/dev/ttyUSB0`, exposed
a Linux PTY, forwarded a full ENTTEC universe, and received telemetry for two
active receivers. The CLI status command also reported the same two receivers.
The existing ESP8266/Mega 660-second acceptance run remains the authoritative
physical DMX/RF evidence; the host daemon's live test confirms the additional
PTY, parser, pacing, transmitter-serial, and telemetry integration path.

The default command is:

```bash
python3 -m wireless_dmx run --config config.example.toml
```

The printed PTY slave path is the port to configure in lighting software. The
daemon owns the physical transmitter at 115200 8N2 and exposes current state
through service snapshots rather than mixing diagnostic text into the ENTTEC
stream.

The 30-minute end-to-end acceptance runner completed successfully on 2026-09-04
with the real transmitter at `/dev/ttyUSB0`, the Arduino Mega monitor at
`/dev/ttyUSB1`, and two active receivers. It submitted 36,000 full-universe DMX
frames at 20 Hz with zero daemon pacer drops. The Mega performed 79,880 physical
DMX checks, with 79,880 passes and zero failures; reported no-data time was
19 ms. The daemon maintained transmitter and virtual-client connectivity and
observed both receivers throughout. Evidence is retained under
`runs/30min-acceptance/`.

The end-to-end acceptance runner is:

```bash
python3 tests/run_30min_acceptance.py \
  --tx-port /dev/ttyUSB0 \
  --mega-port /dev/ttyUSB1 \
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
* Prefer standard-library interfaces in Phase 0.
* Keep I/O adapters replaceable and testable with fakes.
* Use fixed/bounded queues and latest-state semantics.
* Do not enable transmitter text telemetry logging while forwarding ENTTEC
  traffic.
* Hardware verification must identify which behaviors were actually measured.