# Firmware build flags

The firmware helpers accept additional compiler definitions with `--define`.
Definitions are compile-time controls; they do not change an already-flashed
board until that board is rebuilt and flashed.

## Common command form

Compile only:

```bash
./Helpers/flash_receiver.sh --define=-DNAME=value
./Helpers/flash_transmitter.sh --define=-DNAME=value
./Helpers/flash_retransmitter.sh --define=-DNAME=value
```

Compile and flash:

```bash
./Helpers/flash_receiver.sh --define=-DNAME=value -f --port <receiver-port>
./Helpers/flash_transmitter.sh --define=-DNAME=value -f --port <transmitter-port>
```

Always restore and flash a production image after a test-only build.

## Receiver flags

| Definition | Default | Purpose |
|---|---:|---|
| `BATTERY_LOW_ASSERT_MS` | `2000` | Continuous comparator-high time before battery-low assertion. |
| `BATTERY_LOW_CLEAR_MS` | `5000` | Continuous comparator-low time before clearing battery-low. |
| `RX_VALIDATE_TEST_PATTERN` | `0` | Enables the legacy deterministic full-universe content check. Keep disabled for arbitrary production DMX. |
| `PRIORITY_STAGING_TIMEOUT_MS` | `4000` | Lifetime of priority fragments and gate metadata while a complete priority universe is reconstructed. |
| `RECEIVER_FAILSAFE_DEFAULT_MODE` | `RECEIVER_FAILSAFE_HOLD` | Receiver boot default: `HOLD`, `BLACKOUT`, or `DISABLE_LINE`. |
| `RECEIVER_FAILSAFE_DEFAULT_TIMEOUT_SECONDS` | `60` | Receiver boot fail-safe timeout. Runtime daemon configuration can override it. |
| `RECEIVER_DIAGNOSTIC_SERIAL` | `0` | Disables physical DMX output and emits complete reconstructed universes as binary `RDX1` records over UART0 at 115200 8N1, including the promoted fragment source MAC. |
| `RECEIVER_DIAGNOSTIC_BAUD` | `115200` | Diagnostic UART baud rate. Use the same rate with the host reader; `460800` is recommended for high-rate diagnostics. |
| `RECEIVER_DIAGNOSTIC_SILENT_CAPTURE` | `0` | Diagnostic-only mode that validates promoted universes in-device and emits compact capture summaries instead of per-universe `RDX1` records. Requires `RECEIVER_DIAGNOSTIC_SERIAL=1`. |

Example receiver test-pattern build:

```bash
./Helpers/flash_receiver.sh --define=-DRX_VALIDATE_TEST_PATTERN=1
```

## Transmitter flags

| Definition | Default | Purpose |
|---|---:|---|
| `WIRELESS_REFRESH_HZ` | `20` | Native/integrated transmitter production refresh rate. The standalone physical retransmitter uses its own 10 Hz default. |
| `WIRELESS_PRIORITY_REFRESH_HZ` | `1` | Priority fragment cadence. |
| `WIRELESS_TX_OVERHEAD_MS` | `27` | Measured normal-frame overhead used by budget pacing. |
| `WIRELESS_TX_DRAIN_TIMEOUT_MS` | `100` | Bound for a stuck ESP-NOW transmit drain. |
| `TRANSMITTER_TELEMETRY_LOGGING` | `0` | Diagnostic text logging. Keep disabled because UART0 carries binary ENTTEC/management traffic. |
| `TRANSMITTER_VERBOSE_LOGGING` | unset | Development logging. Do not enable during normal UART operation. |
| `TRANSMITTER_MANAGEMENT_ONLY` | unset | Disables ordinary DMX fragments while retaining management and priority DMX. |
| `TRANSMITTER_LOCK_BRIDGE` | unset | Locks the runtime role to bridge; daemon mode requests for management-only are rejected. |
| `TRANSMITTER_LOCK_MANAGEMENT_ONLY` | unset | Locks the runtime role to management-only; daemon mode requests for bridge are rejected. |

Management-only images include the optional passive universe observer. No extra
define is required. The observer listens for ordinary retransmitter fragments,
reconstructs complete universes, and serves them through the management protocol;
it does not make the image a normal-DMX source. The host polls at approximately
4 Hz, so the feature is intended for operator feedback rather than precise
monitoring.

The transmitter helper also supports the Wemos D1 Mini/Pro target, which is useful
for bench or enclosure builds that do not use an ESP-01:

```bash
./Helpers/flash_transmitter.sh --d1
./Helpers/flash_transmitter.sh --d1 --lock-management-only -f --port <port>
```

The management-only image is the recommended image for a monitored standalone
retransmitter. It may send management and priority traffic, but it cannot become
the ordinary-DMX authority when statically locked.

The integrated transmitter helper defaults to the normal bridge role. Select
the optional management role with:

```bash
./Helpers/flash_transmitter.sh --management-only
./Helpers/flash_transmitter.sh --lock-bridge
./Helpers/flash_transmitter.sh --lock-management-only
```

## Standalone re-transmitter

The re-transmitter owns UART0/GPIO3 for physical DMX input and must not call
`Serial.begin()` or write diagnostics to that UART. The DMXUART experiment uses
foreground-polled `DMXUART::read()`, sends only normal three-fragment DMX
packets, and waits for its first complete physical universe before transmitting.
It is constructed with no TX pin, which makes the ESP8266 implementation select
`SERIAL_RX_ONLY`; UART0 RX/GPIO3 remains the DMX input and UART0 TX/GPIO1 remains
available for the optional battery comparator.
The retransmitter pauses DMX UART RX while it queues and drains one complete
three-fragment wireless universe, then resumes RX before waiting the configured
wireless interval. This intentionally permits physical-DMX frames to be lost
while protecting wireless transmission.

```bash
./Helpers/flash_retransmitter.sh
./Helpers/flash_retransmitter.sh --menuconfig
./Helpers/flash_retransmitter.sh --channel 1 --universe 1 --rate 10
```

The helper is compile-only unless `-f` is supplied. `--menuconfig` is a small
interactive Bash configuration menu covering channel, universe, wireless rate,
TX drain timeout, and TX overhead. Its defaults are channel `1`, universe `1`,
10 Hz, 100 ms, and 27 ms respectively. Partial-universe acceptance is now the
only retransmitter mode. Command-line flags remain preferred for repeatable
builds; use `--menuconfig` when selecting options interactively.
Relevant definitions are
`RETRANSMITTER_ESPNOW_CHANNEL`, `RETRANSMITTER_UNIVERSE_ID`,
`RETRANSMITTER_WIRELESS_REFRESH_HZ`, `RETRANSMITTER_TX_DRAIN_TIMEOUT_MS`,
`RETRANSMITTER_DIAGNOSTICS`, `RETRANSMITTER_DIAGNOSTIC_BROADCAST`, and
`RETRANSMITTER_TELEMETRY_ONLY`.

Hardware-control definitions are:

| Definition | Default | Purpose |
|---|---:|---|
| `RETRANSMITTER_DMX_INPUT_ENABLE_PIN` | `-1` | GPIO driving the 2N2222 receiver `/RE` control. Set to `2` to explicitly enable the installed hardware path. |
| `RETRANSMITTER_DMX_INPUT_ENABLE_ACTIVE_HIGH` | `0` | GPIO polarity for logical input enabled. The installed 2N2222 circuit is active-low: GPIO2 `LOW` enables the receiver and `HIGH` disables it. |
| `RETRANSMITTER_BATTERY_MONITOR` | `0` | Enables the GPIO1 comparator input and reports `ok`/`low` telemetry. Disabled builds report `UNKNOWN`. |
| `RETRANSMITTER_BATTERY_PIN` | `1` | Comparator input pin; GPIO1 is available because DMXUART uses `SERIAL_RX_ONLY`. |
| `RETRANSMITTER_BATTERY_LOW_ACTIVE_LOW` | `1` | Comparator polarity. Set to `0` when HIGH means battery-low. |

The helper provides opt-in `--receiver-control`, `--no-receiver-control`,
`--battery-monitor`, `--no-battery-monitor`, and
`--battery-low-active-high`. `--menuconfig` exposes receiver-control enablement,
battery monitoring and comparator polarity in addition to the timing/radio
settings. The menu defaults receiver `/RE` control to disabled.
The production retransmitter uses an absolute 10 Hz universe deadline. It waits
for a fresh complete physical-DMX frame, sends when the deadline is due, and
rebases one period forward after an overrun instead of compressing catch-up
frames. This prevents stale-frame reuse and avoids adding a second full pacing
interval after physical-DMX capture.
It also invokes Arduino CLI with `--clean` so each flashed image is rebuilt from
the requested compile options rather than relying on a shared sketch cache.
The partial build is exported to `Firmware/ReTransmitter/build/partial`. The helper
prints the selected mode, binary path, and SHA-256 before flashing.

The generic `--define DEFINE` option remains available for test-only or future
compile definitions that are not part of the retransmitter's normal menu.

With no extra flags, the retransmitter helper builds the production 10 Hz image
with retransmitter telemetry enabled and diagnostics/diagnostic broadcasts
disabled. `--production` explicitly selects this mode and is mutually exclusive
with `--telemetry-only`. The telemetry-only image is a test variant: it disables
physical-DMX input and normal fragment transmission while retaining the telemetry
scheduler and management reporting. It must never be deployed as a normal
retransmitter. The `--menuconfig` rate default is also 10 Hz. The retransmitter
accepts valid physical DMX frames from
the pinned library's
minimum callback threshold through 512 slots and zero-fills channels after the
received slot count through channel 512. The helper is:

```bash
./Helpers/flash_retransmitter.sh
```

Malformed frames and nonzero start codes remain rejected by the input library.

The processing cost is negligible because the retransmitter already maintains
and clears a 512-channel destination buffer. Partial operation depends on
DMXUART's minimum channel threshold (`UART_MINCHANS_DMX`, currently 24); frames
below that threshold do not produce a usable callback.

## Fault-injection flags

These flags are defined in the Firmware/Transmitter/receiver test-hook comments and are
intended for isolated reconstruction testing:

| Definition | Target | Purpose |
|---|---|---|
| `TEST_DROP_FRAGMENT_INDEX=N` | transmitter | Omits one normal fragment. |
| `TEST_DUPLICATE_FRAGMENT_INDEX=N` | transmitter | Adds a duplicate normal fragment. |
| `TEST_REORDER_FRAGMENTS` | transmitter | Sends normal fragments in reordered sequence. |
| `TEST_CORRUPT_FRAGMENT_INDEX=N` | transmitter | Corrupts one normal payload for legacy validation builds. |
| `TEST_CORRUPT_BYTE=N` | transmitter | Selects the payload byte to corrupt. |
| `TEST_FORCE_SEQUENCE_START=N` | transmitter | Starts normal sequence numbering at a selected value. |
| `TEST_SEQUENCE_WRAP` | transmitter | Starts near the 32-bit sequence rollover. |
| `TEST_DELAYED_FRAGMENT` | transmitter | Sends a stale delayed fragment after a controlled delay. |
| `TEST_SUPPRESS_DMX_TRANSMISSION` | transmitter | Suppresses normal and priority DMX fragments while retaining management/telemetry. Used for finite fail-safe tests. |
| `TEST_INJECT_MALFORMED` | legacy receiver test sketch | Injects malformed input for isolated validation. |

## Monitor flags

The Arduino Mega monitor uses a library-wide build flag rather than a sketch
local define:

```bash
./Helpers/flash_enttec_dmx_monitor.sh -f --port <monitor-port>
```

The helper passes `-DDMX_USE_PORT1`, placing DMX input on Mega USART1 while USB
Serial remains the command/result interface.