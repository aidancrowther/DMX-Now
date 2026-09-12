# Re-transmitter end-to-end hardware test plan

This plan is for the physical setup below. It is intentionally separate from
the host unit suite and compile checks. Do not run the live acceptance runner
until the hardware has been wired, firmware has been flashed, and the operator
has confirmed the setup.

## Topology

```text
/dev/ttyUSB0 -> ESP-01 management transmitter
                    management + priority ESP-NOW only

/dev/ttyUSB1 -> Arduino Mega USB command/result port
                    |
                    +-- USART1 TX / pin 18 -> RS-485 driver -> DMX input line
                                                           |
                                                           v
                                                   ESP-01 re-transmitter
                                                   UART0 RX / GPIO3
                                                           |
                                                    normal ESP-NOW DMX
                                                           |
                                                           v
                                                   ESP-01 diagnostic receiver
                                                           |
/dev/ttyUSB2 <- receiver UART0 TX / GPIO1 diagnostic stream

```

The Mega requires one RS-485 interface:

1. A transmit-only interface for generated DMX.

The diagnostic receiver build completely disables physical DMX output and
instead emits complete reconstructed universes as binary `RDX1` records over
`/dev/ttyUSB2` is the logical-universe monitor after the receiver has been
flashed with this diagnostic build. The default diagnostic baud is 115200; use
the same selected baud in the receiver build and acceptance runner. A 460800
baud build is recommended for high-rate diagnostic capture:

```bash
./helpers/flash_receiver.sh --diagnostic --diagnostic-baud 460800
python tests/run_retransmitter_acceptance.py ... --receiver-baud 460800
```

Build the diagnostic receiver image with:

```bash
./helpers/flash_receiver.sh --diagnostic
```

The diagnostic stream is fixed binary records:

```text
RDX1 | record type | little-endian frame sequence | 512 channel bytes | CRC16
```

The receiver USB serial adapter must be configured for 115200 8N1. This is a
logical reconstructed-DMX observation path; the receiver's physical MAX3485
DMX output remains disabled in this image.

## Software assets

Mega generator/monitor sketch:

```text
tests/retransmitter_end_to_end/retransmitter_end_to_end.ino
```

Compile-only helper:

```bash
./helpers/flash_retransmitter_e2e_mega.sh
```

The helper deliberately has no upload option. Hardware flashing is a separate
operator-controlled step after this plan has been reviewed.

Finite live runner:

```text
wireless_dmx_daemon/tests/run_retransmitter_acceptance.py
```

It opens real serial devices only when explicitly invoked with `--tx-port` and
`--mega-port`. It is not part of the automated test suite and must not be run
during software-only validation.

## Mega command protocol

The Mega uses `/dev/ttyUSB1` at 115200 8N1. The diagnostic receiver uses
`/dev/ttyUSB2` at 115200 8N1.

```text
GENERATE CONST <value>
GENERATE RAMP <base>
GENERATE DYNAMIC <base> <change_ms>
GENERATE SHORT <slots> <base>
STOP
START <settle_seconds> <measure_seconds>
STATUS
ABORT
```

The generated DMX is sent through USART1 as an explicit 513-byte DMX frame
(start code plus channels 1 through 512). The dynamic generator changes channel
1 once per requested interval while keeping the remaining channels deterministic;
this avoids manufacturing torn source frames while still exercising changing
data. Reconstructed data is read from the diagnostic receiver's `/dev/ttyUSB2`
binary stream.

The Mega reports finite results such as:

```text
RESULT seconds=30 generator_slots=512 checked=... pass=... fail=... partial=... max_gap=... no_data=...ms
```

The returned-DMX monitor recognizes DMX BREAK through the USART2 framing-error
bit and publishes only complete frames to the foreground checker. It validates
all 512 output channels. For partial generated input, expected channels after
the generated slot count are zero.

## Safety and preparation checklist

Before applying power or connecting DMX:

- Confirm `/dev/ttyUSB0`, `/dev/ttyUSB1`, and `/dev/ttyUSB2` identities with
  stable USB properties; do not rely on enumeration order alone.
- Disconnect the re-transmitter USB programmer before connecting physical DMX
  to its UART0/GPIO3 input.
- Keep the re-transmitter RS-485 transceiver receive-only.
- Keep the Mega generator transceiver transmit-only during generated-DMX tests.
- Keep the Mega returned-DMX monitor transceiver receive-only.
- Use separate RS-485 transceivers for the Mega output and Mega monitor input.
- Verify RS-485 A/B polarity, termination, signal reference, and voltage levels.
- Do not enable two RS-485 drivers on the same line.
- Avoid conflicting power sources and observe the receiver board's lack of
  galvanic isolation.
- Disconnect the receiver from fixtures before applying disruptive output or
  locate commands.

## Firmware roles for initial testing

Initial conservative setup:

```text
Management transmitter: TRANSMITTER_LOCK_MANAGEMENT_ONLY
Re-transmitter:         strict 512-slot build
Receiver:               production receiver firmware
Mega:                   retransmitter_end_to_end sketch
```

Compile commands:

```bash
./helpers/flash_transmitter.sh --lock-management-only
./helpers/flash_retransmitter.sh --channel 1 --universe 1 --rate 20
./helpers/flash_receiver.sh
./helpers/flash_retransmitter_e2e_mega.sh
```

These commands compile only. Flashing is intentionally not performed by the
software preparation workflow.

All ESP-NOW devices must use the same channel and universe settings. The
re-transmitter is the only normal-DMX authority. The management transmitter is
allowed management/control packets and explicit priority traffic only.

## Test phases

### 1. Wired source baseline

Generate constant values, ramps, and boundary values. Confirm that the Mega
returned-DMX monitor sees the same values after the wireless receiver path.
Check channels 1, 2, 255, 256, 511, and 512 explicitly.

Pass criteria:

- `checked > 0`
- `fail = 0`
- all 512 channels match
- no mixed-frame values

### 2. Strict partial rejection

With the default strict re-transmitter image:

1. Establish a complete 512-slot value of 77.
2. Generate a shorter physical universe of 99.
3. Confirm the receiver remains at the previous complete universe.
4. Restore a complete 512-slot universe of 99.
5. Confirm recovery with no mixed frame.

### 3. Partial zero-fill

Reflash the re-transmitter with:

```bash
./helpers/flash_retransmitter.sh --accept-partial
```

Test practical lengths supported by the pinned input library, including 25,
100, 255, 256, 511, and 512 slots. Confirm channels after the received count
are zero and do not retain values from a previous longer frame.

The pinned `LXESP8266DMX` library has a minimum callback threshold, so very
short frames below that threshold are not expected to produce callbacks.

### 4. Input interruption and recovery

Stop and restart the Mega DMX generator, then reset the re-transmitter. Confirm
the receiver holds the last complete universe during source loss and accepts a
new complete universe after recovery.

### 5. Management-only coexistence

Run the daemon in management-only mode against `/dev/ttyUSB0`. Confirm:

- telemetry discovery works;
- normal retransmitted DMX remains unchanged;
- fail-safe/output controls behave as documented;
- management transmitter absence does not stop normal retransmission;
- daemon/transmitter reconnect does not corrupt the normal universe.

The extended dynamic soak uses:

```bash
python3 wireless_dmx_daemon/tests/run_retransmitter_acceptance.py \
  --tx-port /dev/ttyUSB0 --mega-port /dev/ttyUSB1 \
  --receiver-port /dev/ttyUSB2 --receiver-baud 460800 \
  --seconds 900 --pattern dynamic --change-ms 1000
```

The runner samples daemon state once per second but leaves telemetry requests
under service control. With `telemetry_interval_seconds = 10`, the completed
900-second run produced 91 requests and 91 reports, with zero telemetry failures.
It produced 7,991 valid diagnostic normal-universe records and zero invalid
promotions. A diagnostic CRC count before content synchronization may be
nonzero due to startup stream alignment; CRC errors after the first valid
dynamic promotion fail the run.

### 6. Priority and gates

Use the management-only daemon to send a priority universe and gate metadata.
Confirm priority ACKs, locked-channel behavior, open-channel following, and
normal retransmission after priority completion.

The gate distinction is important for a standalone retransmitter:

- `MANAGEMENT_ONLY` is a daemon-side soft gate. It blocks ordinary source frames
  that enter the daemon, but cannot filter normal packets generated independently
  by the physical retransmitter. Its host-side behavior is covered by the service
  tests and must not be treated as receiver-side persistence.
- `LOCKED` is receiver-side hard-gate metadata carried by a priority transaction.
  Test channels on both sides of fragment boundaries, require
  `PRIORITY_COMPLETE_GATE_APPLIED`, verify locked values persist through normal
  retransmitter traffic, then explicitly clear the mask and verify normal output
  recovery.

### 7. Runtime mode and lock behavior

Only after the locked management-only baseline passes:

- test runtime-capable transmitter mode changes;
- test locked bridge rejection of management-only requests;
- test locked management-only rejection of bridge requests.

Never intentionally operate two normal-DMX authorities on the same universe.

## Acceptance evidence

Record for each phase:

- firmware/build commands and commit ID;
- USB device identity mapping;
- ESP-NOW channel and universe;
- Mega command transcript;
- `RESULT` line;
- daemon mode and transmitter-mode response;
- receiver ID and telemetry state;
- intentional interruptions and recovery times;
- photos or wiring notes for RS-485 direction/termination.

Hardware validation must be marked separately from compilation and host tests.