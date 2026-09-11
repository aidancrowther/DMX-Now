# Firmware build flags

The firmware helpers accept additional compiler definitions with `--define`.
Definitions are compile-time controls; they do not change an already-flashed
board until that board is rebuilt and flashed.

## Common command form

Compile only:

```bash
./helpers/flash_receiver.sh --define=-DNAME=value
./helpers/flash_transmitter.sh --define=-DNAME=value
```

Compile and flash:

```bash
./helpers/flash_receiver.sh --define=-DNAME=value -f --port <receiver-port>
./helpers/flash_transmitter.sh --define=-DNAME=value -f --port <transmitter-port>
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

Example receiver test-pattern build:

```bash
./helpers/flash_receiver.sh --define=-DRX_VALIDATE_TEST_PATTERN=1
```

## Transmitter flags

| Definition | Default | Purpose |
|---|---:|---|
| `WIRELESS_REFRESH_HZ` | `20` | Normal wireless refresh rate. The validated production rate is 20 Hz. |
| `WIRELESS_PRIORITY_REFRESH_HZ` | `1` | Priority fragment cadence. |
| `WIRELESS_TX_OVERHEAD_MS` | `27` | Measured normal-frame overhead used by budget pacing. |
| `WIRELESS_TX_DRAIN_TIMEOUT_MS` | `100` | Bound for a stuck ESP-NOW transmit drain. |
| `TRANSMITTER_TELEMETRY_LOGGING` | `0` | Diagnostic text logging. Keep disabled because UART0 carries binary ENTTEC/management traffic. |
| `TRANSMITTER_VERBOSE_LOGGING` | unset | Development logging. Do not enable during normal UART operation. |

## Fault-injection flags

These flags are defined in the transmitter/receiver test-hook comments and are
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
./helpers/flash_enttec_dmx_monitor.sh -f --port <monitor-port>
```

The helper passes `-DDMX_USE_PORT1`, placing DMX input on Mega USART1 while USB
Serial remains the command/result interface.