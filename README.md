# ESP8266 Wireless DMX

ESP8266-based wireless DMX512 system using QuickESPNow, MAX3485 RS-485
transceivers, and a Linux host daemon. A transmitter receives a DMX universe
from lighting software and broadcasts the latest complete universe to multiple
battery-powered ESP-01 receivers. Each receiver regenerates standard wired DMX
for its connected fixture or DMX chain.

## Project attribution

The software in this project is vibe coded with AI assistance. The receiver,
transmitter, and supporting electronics hardware were designed by me.

## System overview

```text
QLC+ / lighting software
        |
        | Art-Net, or ENTTEC-compatible virtual serial
        v
Linux Wireless DMX daemon
        |
        | 115200 8N2
        v
ESP8266 transmitter
        |
        | QuickESPNow broadcast
        v
ESP-01 receivers
        |
        | MAX3485 RS-485
        v
DMX fixtures
```

The wireless transport uses latest-state behavior. Receivers retain their last
complete universe if a wireless update or fragment is missed. Obsolete pending
universes are discarded instead of being retransmitted.

## Validated operating mode

The supported production mode is:

```text
Wireless refresh:       20 Hz
Transmitter serial:     115200 baud, 8 data bits, no parity, 2 stop bits
DMX universe:            512 channels
Wireless transport:     QuickESPNow ESP-NOW broadcast
Receiver output:         DMX512, 250000 baud, 8N2
```

The 20 Hz setting is the validated reliable RF operating point. Higher rates
can be built for experimentation, but are not the production reliability
target. The host daemon uses latest-state pacing to reduce faster input streams
to the configured wireless rate.

## Host daemon

The host daemon is located at:

```text
./wireless_dmx_daemon/
```

It provides:

* Linux virtual serial port for ENTTEC-compatible applications.
* Art-Net ArtDMX input for network-based applications such as QLC+.
* Configurable transmitter serial connection and automatic reconnection.
* 20 Hz latest-state DMX pacing.
* Feature 11 receiver telemetry collection.
* Online, stale, and offline receiver states.
* DMX and telemetry statistics.
* A btop-like terminal dashboard.
* Optional Arduino Mega hardware-monitor controls.

### Requirements

* Linux host for the current virtual serial backend.
* Python 3.11 or newer.
* `pyserial`.
* ESP8266 transmitter connected as a serial device.

Install the daemon locally:

```bash
cd wireless_dmx_daemon
python3 -m pip install .
```

Or run it directly from the project directory without installation:

```bash
cd wireless_dmx_daemon
python3 -m wireless_dmx_dashboard
```

## Configuration

The example configuration is:

```text
./wireless_dmx_daemon/config.example.toml
```

The safe default configuration is:

```text
./wireless_dmx_daemon/default.conf
```

If no configuration path is supplied, the daemon searches for `default.conf`
in the current directory and then in the daemon directory.

Important settings:

```toml
[transmitter]
device = "/dev/ttyUSB0"
baud = 115200
data_bits = 8
parity = "none"
stop_bits = 2

[pacer]
enabled = true
rate_hz = 20.0
maximum_rate_hz = 20.0
allow_experimental_rates = false

[virtual_port]
enabled = true
requested_path = "/tmp/wireless-dmx"

[artnet]
enabled = true
bind_host = "0.0.0.0"
port = 6454
universe = 0

[input]
source_policy = "latest"
```

Both virtual serial and Art-Net can be enabled at the same time. Source policy
options are:

```text
latest  Accept the most recent valid frame from either source
serial  Accept only virtual serial input
artnet  Accept only Art-Net input
```

## QLC+ / Art-Net setup

Art-Net is the recommended QLC+ integration because it does not require QLC+ to
discover a physical USB Enttec interface.

1. Start the daemon dashboard or service.
2. In QLC+, open the input/output configuration.
3. Enable the Art-Net output plugin.
4. Select the daemon host as the Art-Net destination.
5. Configure Universe 0.
6. Use UDP port 6454.
7. Start playback/output in QLC+.

Start the dashboard with:

```bash
cd wireless_dmx_daemon
python3 wireless_dmx_dashboard.py --config default.conf
```

For a remote QLC+ host, replace the destination with the Linux host’s network
address. Ensure UDP port 6454 is allowed through the host firewall.

## Virtual serial setup

The daemon creates a Linux PTY and exposes the configured path, normally:

```text
/tmp/wireless-dmx
```

The actual PTY path is also displayed by the dashboard and daemon startup. A
serial application can be configured to open that path using:

```text
115200 baud, 8 data bits, no parity, 2 stop bits
```

The PTY is a compatibility input for applications that can manually select a
serial path. Applications that only enumerate physical USB DMX interfaces may
not list it; use Art-Net in that case.

## Dashboard

Launch:

```bash
cd wireless_dmx_daemon
python3 wireless_dmx_dashboard.py --config default.conf
```

The dashboard shows:

* Daemon and transmitter connection health.
* Virtual serial client state.
* Art-Net enablement and port.
* DMX input/submission/drop counters.
* Receiver battery, RSSI, link, freshness, and universe counters.
* Recent daemon events.

Main controls:

| Key | Action |
|---|---|
| `d` | Start/stop the daemon |
| `r` | Request immediate telemetry |
| `s` | Open configuration setup |
| `x` | Open Advanced hardware testing |
| `l` | Toggle event log |
| `q` | Quit cleanly |

The setup editor can change and atomically save configuration fields including
Art-Net settings. Press `e` to edit a selected value, `w` to save, and `x` to
cancel.

Mega monitoring and 30-minute acceptance testing are intentionally located in
the Advanced menu because they are development and validation functions rather
than normal release controls.

## Telemetry

Receivers periodically broadcast Feature 11 telemetry. The daemon reports:

* Receiver ID and MAC address.
* Battery-low state.
* Transmitter-observed and receiver-observed RSSI.
* Last completed wireless sequence.
* Complete and incomplete universe counters.
* Malformed packet count.
* Time since last valid universe.
* Receiver uptime and firmware version.

Telemetry requests and reports use the binary Feature 11 management protocol.
Diagnostic text logging is not enabled on the transmitter during normal
operation because its UART carries the ENTTEC/management binary stream.

## Hardware

Each receiver is designed around:

* ESP-01 / ESP8266.
* MAX3485 3.3 V RS-485 transceiver.
* 1-cell Li-ion/LiPo battery.
* TP4056 charger/protection module.
* 3.3 V buck/boost regulator.
* External comparator-based low-battery detector.

Receiver pin allocation:

```text
GPIO1 / UART TX -> DMX data / MAX3485 DI
GPIO2           -> MAX3485 DE through inverting transistor stage
GPIO3 / UART RX <- active-high low-battery signal
GPIO0           -> reserved for boot requirements
```

The receiver keeps DMX output disabled during startup and enables it only after
QuickESPNow, buffers, and espDMX have been initialized.

## Building firmware

The project uses Arduino ESP8266 and `arduino-cli`, not PlatformIO.

Compile and flash the transmitter:

```bash
./flash_transmitter.sh
./flash_transmitter.sh -f --port /dev/ttyUSB0
```

Compile and flash the receiver:

```bash
./flash_receiver.sh
./flash_receiver.sh -f --port /dev/ttyUSB1
```

Required local libraries are stored under:

```text
./libraries/QuickESPNow/
./libraries/espDMX/
./libraries/WirelessDMX/
```

## Testing

Host daemon tests:

```bash
cd wireless_dmx_daemon
python3 -m unittest discover -s tests -v
```

The repository also contains hardware test plans and evidence for wireless
fragmentation, receiver reconstruction, telemetry, ENTTEC input, Art-Net input,
and 20 Hz operation.

Development history, implementation decisions, test results, and progress are
maintained separately in:

```text
./DEVELOPMENT_PROGRESS.md
```

## Limitations

* The current virtual serial backend targets Linux.
* QLC+ may not enumerate a PTY as a USB Enttec interface; use Art-Net instead.
* 20 Hz is the validated reliable wireless rate.
* Experimental wireless rates above 20 Hz are not production-validated.
* ESP-NOW transport is unencrypted in the current QuickESPNow configuration.
* Receiver hardware is not galvanically isolated from USB charging power; follow
  the documented charging/DMX connection precautions.