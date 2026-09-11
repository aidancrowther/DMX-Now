# DMX Now

DMX Now is an ESP8266-based DMX512 system. A host daemon accepts DMX from
Art-Net or an ENTTEC-compatible serial client, sends the latest complete
universe to a wireless transmitter, and distributes it over QuickESPNow to any
number of battery-powered receivers. Each receiver regenerates DMX512 through
an RS-485 transceiver.

```text
Lighting software -> host daemon -> ESP8266 transmitter
                                      |
                                      +-- QuickESPNow --> one or more receivers
                                                           |
                                                           +--> DMX512 fixtures
```

## Supported operating mode

The validated production target is:

```text
Wireless refresh:   20 Hz
Host transmitter:   115200 baud, 8N2
Universe:            512 channels
Wireless transport: QuickESPNow / ESP-NOW
Receiver output:    DMX512, 250000 baud, 8N2
```

The transport is latest-state based. A receiver retains its last complete
universe when a fragment or wireless update is missed; incomplete universes are
discarded rather than promoted.

## Features

- Streaming ENTTEC DMX input and Art-Net ArtDMX input.
- Optional raw-DMX virtual serial input accepting complete 512-byte universes.
- Raw-DMX incomplete-burst timeout, defaulting to 1 second.
- Bounded latest-state pacing at the validated 20 Hz rate.
- Receiver telemetry with link freshness, battery, RSSI, sequence, counters,
  firmware, and fail-safe state.
- Targeted priority complete-universe delivery with bounded retries and ACKs.
- Runtime channel gates (`OPEN`, `MANAGEMENT_ONLY`, and `LOCKED`).
- Runtime receiver fail-safe modes:
  - `hold`: retain the last complete universe;
  - `blackout`: output a zero universe after the timeout;
  - `disable_line`: disable the RS-485 driver after the timeout.
- Automatic recovery after a new complete universe.
- Linux PTY input and a terminal management dashboard.
- Persistent host-side receiver friendly names editable from the dashboard.

## Repository layout

```text
receiver/                 ESP8266 receiver firmware
transmitter/              ESP8266 transmitter firmware
libraries/                pinned QuickESPNow, espDMX, and shared protocol code
wireless_dmx_daemon/      Linux host daemon and tests
tests/                    firmware and hardware monitor sketches
helpers/                  compile/flash helpers
docs/                     detailed architecture, protocol, and validation docs
Hardware/                 receiver schematic
DEVELOPMENT_PROGRESS.md   development history and status
```

## Hardware

Each receiver uses an ESP-01/ESP8266, MAX3485 RS-485 transceiver, battery
power/charging circuitry, and an external low-battery comparator. The receiver
uses GPIO1 for DMX TX, GPIO2 for inverted MAX3485 driver enable, and GPIO3 for
the active-high low-battery signal. See `docs/hardware.md` and the schematic in
`Hardware/1-Schematic_ESP DMX.json`.

## Build and flash

The project uses `arduino-cli`, not PlatformIO:

```bash
./helpers/flash_transmitter.sh
./helpers/flash_receiver.sh
```

Add `-f --port <device>` to flash a selected board. The helpers support
`--define` for compile-time test settings. Never leave a test-only transmitter
or receiver define enabled in a production image.

## Host daemon

```bash
cd wireless_dmx_daemon
python3 -m pip install .
wireless-dmx run --config configs/config.example.toml
```

The daemon prints the Linux PTY path. Configure a serial-capable application to
use that path, or use Art-Net Universe 0 over UDP port 6454. The complete daemon
configuration is documented in `docs/daemon.md` and demonstrated in
`wireless_dmx_daemon/configs/config.example.toml`.

Dashboard configurations are stored under `wireless_dmx_daemon/configs/`. The
dashboard can select a configuration interactively when launched without
`--config`. The CLI and scripted dashboard forms continue to accept
`--config <path>`.

The optional raw-DMX input creates a second PTY and accepts one complete
512-byte universe per burst. Configure it under `[raw_virtual_port]` and select
it with `[input] source_policy = "raw_serial"`; incomplete bursts expire after
1 second by default.

## Receiver fail-safe configuration

```toml
[receiver_failsafe]
mode = "hold"          # hold, blackout, or disable_line
timeout_seconds = 60   # validated range: 30..3600
```

Settings are sent at runtime and are not persisted in receiver flash. Receivers
start with compile-time defaults and the daemon reapplies its configured
generation after startup, transmitter reconnect, receiver discovery, or
receiver reboot. Detailed semantics and finite validation procedures are in
`docs/receiver-failsafe.md`.

## Tests

Run the host suite with:

```bash
cd wireless_dmx_daemon
python3 -m pytest -q
```

The detailed test catalogue is in `docs/testing.md`. Hardware-specific results
are kept separately in `docs/lab-validation.md`; they are evidence for one
validated setup, not a requirement that every deployment have the same number
of receivers, USB paths, or monitor hardware.

The dashboard hotkey reference is in `docs/daemon.md`.

## Limitations

- The current virtual serial backend targets Linux.
- Applications that only enumerate physical USB DMX interfaces may not list a
  Linux PTY; use Art-Net in that situation.
- Wireless rates above 20 Hz are experimental and not production-validated.
- ESP-NOW is unencrypted in the current QuickESPNow configuration.
- Receiver charging and DMX equipment require the isolation precautions in the
  hardware documentation.