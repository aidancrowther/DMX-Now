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

## Supported operating modes

The project supports the following operating modes and hardware roles.

### 1. Host bridge mode — normal production operation

The Linux host daemon accepts a DMX universe from one of its configured inputs,
the integrated ESP8266 transmitter broadcasts it over QuickESPNow, and one or
more ESP8266 receivers regenerate DMX512 for fixtures.

```text
Host input -> Linux daemon -> ESP8266 transmitter
                              |
                              +-- QuickESPNow -> ESP8266 receiver(s) -> DMX512
```

The validated native/integrated transmitter target is 20 Hz:

```text
Wireless refresh:   20 Hz
Host transmitter:   115200 baud, 8N2
Universe:            512 channels
Wireless transport: QuickESPNow / ESP-NOW
Receiver output:    DMX512, 250000 baud, 8N2
```

The host can receive DMX through an ENTTEC-compatible serial PTY, Art-Net
ArtDMX, or an optional raw-DMX virtual PTY. The daemon also provides the
terminal dashboard, receiver management, priority traffic, channel gates, and
fail-safe configuration.

### 2. Management-only mode

The daemon and integrated transmitter can run without emitting ordinary DMX.
This mode is intended for a deployment where another device owns normal DMX,
especially the standalone physical-DMX retransmitter below. Telemetry,
receiver discovery, fail-safe settings, output control, locate, channel gates,
and explicit priority traffic remain available.

Start the daemon with either:

```bash
wireless-dmx run --management-only --config configs/config.example.toml
# or set [daemon] mode = "management_only" in the configuration
```

The integrated transmitter can also be built as a locked management-only image
with `./helpers/flash_transmitter.sh --lock-management-only`.

### 3. Standalone physical-DMX retransmitter

The standalone ESP8266 retransmitter receives physical DMX through a
receive-only RS-485 interface on UART0/GPIO3 and broadcasts the existing normal
three-fragment wireless protocol directly to the receivers. It does not require
the Linux daemon, a host transmitter, or a management transmitter for normal
operation.

Its production target is 10 Hz. It accepts complete and supported partial
physical-DMX frames from 24 through 512 slots, zero-filling the remaining
channels through channel 512. The retransmitter never drives its physical DMX
input line and has diagnostics disabled in the production image.

```text
Physical DMX source -> receive-only RS-485 -> ESP8266 retransmitter
                                               |
                                               +-- ESP-NOW -> receiver(s) -> fixtures
```

See [`docs/retransmitter-deployment.md`](docs/retransmitter-deployment.md) for
wiring, production flashing, radio configuration, recovery, and validation.

### 4. Monitored retransmitter deployment

The retransmitter can be paired with a separate locked management-only ESP8266
transmitter. The physical retransmitter remains the sole normal-DMX authority;
the management transmitter provides receiver telemetry and control only. This
mode supports remote fail-safe configuration, receiver output control, locate,
channel gates, and explicit priority operations without creating a competing
ordinary-DMX source.

### 5. Arduino Mega USB-controlled DMX controller using `DMXSerial`

`tests/mega_dmx_controller/` provides a simple local DMX source for bench
testing. It uses the `DMXSerial` library on Mega USART1, with DMX output on pin
18 and the USB connection available on `/dev/ttyUSB1` at 115200 baud, 8N1.

Flash it with:

```bash
./helpers/flash_mega_dmx_controller.sh -f --port /dev/ttyUSB1
```

Enter newline-terminated commands over USB:

```text
<channel 1-512> <value 0-255>
1 255
24 128
clear
status
help
```

### 6. Arduino Mega USB-controlled DMX controller using `DmxSimple`

`tests/mega_dmxsimple_controller/` is the equivalent local controller using
the `DmxSimple` library. Unlike the `DMXSerial` variant, it outputs DMX through
Mega digital pin 3 and does not use USART1. The USB command interface is still
available at 115200 baud, 8N1.

Flash it with:

```bash
./helpers/flash_mega_dmxsimple_controller.sh -f --port /dev/ttyUSB1
```

It accepts the same `channel value`, `clear`, `status`, and `help` commands.

### Wireless transport behavior

The wireless transport is latest-state based. A receiver retains its last
complete universe when a fragment or wireless update is missed; incomplete
universes are discarded rather than promoted. The retransmitter and native
transmitter use the same shared packet protocol.

## Functions

- Receives DMX through ENTTEC-compatible serial input, Art-Net ArtDMX, or an
  optional raw-DMX virtual serial input accepting complete 512-byte universes.
- Expires incomplete raw-DMX bursts after 1 second without changing the active
  universe.
- Paces native/integrated wireless transmission at the validated 20 Hz rate and
  standalone retransmission at the validated 10 Hz rate.
- Reconstructs fragmented 512-channel universes safely on receivers using
  staging and active buffers; incomplete data is never promoted.
- Retains the last complete universe through temporary wireless loss and
  automatically recovers when a new valid universe arrives.
- Reports receiver telemetry including link freshness, battery, RSSI, sequence,
  counters, firmware, and fail-safe state.
- Delivers targeted priority complete universes with bounded retries and ACKs.
- Supports runtime channel gates: `OPEN`, `MANAGEMENT_ONLY`, and `LOCKED`.
- Supports receiver fail-safe modes:
  - `hold`: retain the last complete universe;
  - `blackout`: output a zero universe after the timeout;
  - `disable_line`: disable the RS-485 driver after the timeout.
- Provides receiver output enable/disable control and a temporary locate function
  for identifying hardware.
- Provides persistent receiver friendly names in the host configuration.
- Provides a Linux PTY input path and terminal dashboard with manual universe
  editing, normal/priority transmission, channel gates, receiver selection,
  output control, locate, telemetry, and validation actions.
- Converts physical DMX to the normal wireless protocol in standalone
  retransmitter mode, including partial-frame zero-fill through channel 512.
- Provides two simple Mega bench controllers that set individual channels over
  USB and continuously transmit a 512-channel DMX universe.

## Repository layout

```text
receiver/                 ESP8266 receiver firmware
transmitter/              ESP8266 transmitter firmware
retransmitter/             UART0 physical DMX -> normal ESP-NOW firmware
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
./helpers/flash_retransmitter.sh
```

The normal transmitter helper defaults to bridge mode. Build the optional
management-only role with `./helpers/flash_transmitter.sh --management-only`.
The daemon defaults to bridge mode; use `[daemon] mode = "management_only"` or
`wireless-dmx run --management-only` for management-only operation. The
management role never emits ordinary DMX, but priority/gate transactions remain
available.

Add `-f --port <device>` to flash a selected board. The helpers support
`--define` for compile-time test settings. Never leave a test-only transmitter
or receiver define enabled in a production image.

For physical retransmitter wiring, deployment roles, optional management-only
monitoring, and production/test image recovery, see
[`docs/retransmitter-deployment.md`](docs/retransmitter-deployment.md).

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

## Project note

This is a vibe-coded project: AI-assisted development was used extensively for
implementation, documentation, and validation support. The hardware design,
wiring, and physical engineering decisions were managed by me.