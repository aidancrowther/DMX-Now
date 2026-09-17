# Firmware build flags

The firmware helpers accept additional compiler definitions with `--define`.
Definitions are compile-time controls; they do not change an already-flashed
board until that board is rebuilt and flashed.

## Common command form

Compile only:

```bash
./helpers/flash_receiver.sh --define=-DNAME=value
./helpers/flash_transmitter.sh --define=-DNAME=value
./helpers/flash_retransmitter.sh --define=-DNAME=value
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
| `RECEIVER_DIAGNOSTIC_SERIAL` | `0` | Disables physical DMX output and emits complete reconstructed universes as binary `RDX1` records over UART0 at 115200 8N1, including the promoted fragment source MAC. |
| `RECEIVER_DIAGNOSTIC_BAUD` | `115200` | Diagnostic UART baud rate. Use the same rate with the host reader; `460800` is recommended for high-rate diagnostics. |
| `RECEIVER_DIAGNOSTIC_SILENT_CAPTURE` | `0` | Diagnostic-only mode that validates promoted universes in-device and emits compact capture summaries instead of per-universe `RDX1` records. Requires `RECEIVER_DIAGNOSTIC_SERIAL=1`. |

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
| `TRANSMITTER_MANAGEMENT_ONLY` | unset | Disables ordinary DMX fragments while retaining management and priority DMX. |
| `TRANSMITTER_LOCK_BRIDGE` | unset | Locks the runtime role to bridge; daemon mode requests for management-only are rejected. |
| `TRANSMITTER_LOCK_MANAGEMENT_ONLY` | unset | Locks the runtime role to management-only; daemon mode requests for bridge are rejected. |

The integrated transmitter helper defaults to the normal bridge role. Select
the optional management role with:

```bash
./helpers/flash_transmitter.sh --management-only
./helpers/flash_transmitter.sh --lock-bridge
./helpers/flash_transmitter.sh --lock-management-only
```

## Standalone re-transmitter

The re-transmitter owns UART0/GPIO3 for physical DMX input and must not call
`Serial.begin()` or write diagnostics to that UART. The DMXUART experiment uses
foreground-polled `DMXUART::read()`, sends only normal three-fragment DMX
packets, and waits for its first complete physical universe before transmitting.
The retransmitter keeps DMX UART RX active while it queues and drains one
complete three-fragment wireless universe. Each burst uses an immutable snapshot
so newly received physical-DMX frames cannot mix with the in-flight universe.
The previous pause behavior remains available for A/B testing with
`RETRANSMITTER_PAUSE_RX_DURING_TX=1`.

```bash
./helpers/flash_retransmitter.sh
./helpers/flash_retransmitter.sh --menuconfig
./helpers/flash_retransmitter.sh --channel 1 --universe 1 --rate 20
```

The helper is compile-only unless `-f` is supplied. `--menuconfig` is a small
interactive Bash configuration menu covering channel, universe, wireless rate,
TX drain timeout, and TX overhead. Partial-universe acceptance is now the only
retransmitter mode. Command-line flags remain preferred for repeatable builds.
Relevant definitions are
`RETRANSMITTER_ESPNOW_CHANNEL`, `RETRANSMITTER_UNIVERSE_ID`,
`RETRANSMITTER_WIRELESS_REFRESH_HZ`, `RETRANSMITTER_TX_DRAIN_TIMEOUT_MS`,
`RETRANSMITTER_TX_OVERHEAD_MS`, `RETRANSMITTER_DIAGNOSTICS`,
`RETRANSMITTER_DIAGNOSTIC_BROADCAST`, and `RETRANSMITTER_PAUSE_RX_DURING_TX`.
The A/B scheduler flags `RETRANSMITTER_SERIALIZE_FRAGMENTS`,
`RETRANSMITTER_FRAGMENT_SPACING_MS`, `RETRANSMITTER_DISABLE_WIFI_SLEEP`, and
`RETRANSMITTER_DIAGNOSTIC_IDLE_POLL_ONLY` are also available through the
generic `--define` option. Serialized mode admits one ESP-NOW fragment only
when the transport is idle, spaces fragment deadlines explicitly, and uses an
absolute universe cadence; it never advances past a busy fragment admission.
The normal queued retransmitter pacing
uses the requested interval minus `RETRANSMITTER_TX_OVERHEAD_MS`, measured from
the previous wireless drain completion.
It also invokes Arduino CLI with `--clean` so each flashed image is rebuilt from
the requested compile options rather than relying on a shared sketch cache.
The partial build is exported to `retransmitter/build/partial`. The helper
prints the selected mode, binary path, and SHA-256 before flashing.

The generic `--define DEFINE` option remains available for test-only or future
compile definitions that are not part of the retransmitter's normal menu.

The re-transmitter accepts valid physical DMX frames from the pinned library's
minimum callback threshold through 512 slots and zero-fills channels after the
received slot count through channel 512. The helper is:

```bash
./helpers/flash_retransmitter.sh
```

Malformed frames and nonzero start codes remain rejected by the input library.

## Receiver promotion invariant

The receiver stages every normal universe in a separate 512-byte buffer. A
universe is eligible for promotion only after all canonical fragment tiles cover
all 512 bytes for one sequence. Malformed, overlapping, incomplete, stale, and
duplicate fragment traffic cannot alter the active universe. Silent diagnostic
images add deterministic content/source validation **before** the staging buffer
is swapped into the active buffer; rejected complete candidates therefore do not
increment `completeUniverses`, change the active sequence, or reach the DMX
output. `RDS1` reports `complete_candidates`, `rejected_complete`, `promotions`,
and `matching` so the invariant can be checked after every test. In silent
diagnostic mode, `corrupt` and `rejected_complete` count complete candidates
that were rejected before promotion; they are not promoted-corruption counts.
The required safety invariant is `promotions == matching` and
`complete_candidates == promotions + rejected_complete`.

The deeper validation sequence should include normal 512-slot controls followed
by isolated fault-injection runs for dropped, duplicated, reordered, corrupted,
stale, and malformed fragments. Each fault run must show no new promotion of an
improper universe, while a subsequent valid frame must still promote normally.

The processing cost is negligible because the retransmitter already maintains
and clears a 512-channel destination buffer. Partial operation depends on
DMXUART's minimum channel threshold (`UART_MINCHANS_DMX`, currently 24); frames
below that threshold do not produce a usable callback.

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