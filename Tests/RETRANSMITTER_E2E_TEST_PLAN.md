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
./Helpers/flash_receiver.sh --diagnostic --diagnostic-baud 460800
python Tests/run_retransmitter_acceptance.py ... --receiver-baud 460800
```

Build the diagnostic receiver image with:

```bash
./Helpers/flash_receiver.sh --diagnostic
```

The diagnostic stream is fixed binary records:

```text
RDX1 | record type | little-endian frame sequence | source MAC (6 bytes) |
     | 512 channel bytes | CRC16
```

The receiver USB serial adapter must be configured for 115200 8N1. This is a
logical reconstructed-DMX observation path; the receiver's physical MAX3485
DMX output remains disabled in this image.

Diagnostic records include the ESP-NOW source MAC for the promoted fragment
sequence. This is important when more than one normal-DMX authority may be
within radio range: content validation without source attribution cannot prove
which transmitter produced a promotion.

## Software assets

Mega generator/monitor sketch:

```text
Tests/retransmitter_end_to_end/retransmitter_end_to_end.ino
```

Compile-only helper:

```bash
./Helpers/flash_retransmitter_e2e_mega.sh
```

The helper deliberately has no upload option. Hardware flashing is a separate
operator-controlled step after this plan has been reviewed.

Finite live runner:

```text
Host Software/wireless_dmx_daemon/tests/run_retransmitter_acceptance.py
```

It opens real serial devices only when explicitly invoked with `--tx-port` and
`--mega-port`. It is not part of the automated test suite and must not be run
during software-only validation.

## Mega command protocol

The Mega uses `/dev/ttyUSB1` at 115200 8N1. The diagnostic receiver uses
`/dev/ttyUSB2` at 460800 8N1.

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
Re-transmitter:         production 10 Hz telemetry build
Receiver:               production receiver firmware
Mega:                   retransmitter_end_to_end sketch
```

Compile commands:

```bash
./Helpers/flash_transmitter.sh --lock-management-only
./Helpers/flash_retransmitter.sh --production --channel 1 --universe 1 --rate 10
./Helpers/flash_receiver.sh
./Helpers/flash_retransmitter_e2e_mega.sh
```

These commands compile only. Flashing the retransmitter itself requires its
ESP8266 programming port; the host management transmitter and diagnostic
receiver use their separate ports.

All ESP-NOW devices must use the same channel and universe settings. The
The re-transmitter is the only normal-DMX authority. The management transmitter is
allowed management/control packets and explicit priority traffic only.

The production retransmitter also reports best-effort telemetry: physical-DMX
freshness and slot count, input/effective state, locate state, wireless frame
counters, and control generation. Telemetry must never delay a DMX fragment or
create a catch-up burst. Use `--telemetry-only` only for scheduler/control tests;
that image disables physical-DMX input and normal retransmission.

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

### 2. Partial zero-fill and corruption detection

Build and flash the sole supported partial-universe retransmitter image:

```bash
./Helpers/flash_retransmitter.sh -f --port <retransmitter-programmer>
```

Test practical lengths supported by the pinned input library, including 25,
100, 255, 256, 511, and 512 slots. Confirm channels after the received count
are zero and do not retain values from a previous longer frame.

The pinned `DMXUART` library has a minimum callback threshold, so very
short frames below that threshold are not expected to produce callbacks.

Partial mode accepts callback-complete DMX frames from the library's minimum
slot threshold through 512 slots, copies the completed frame, and zero-fills
the remaining channels. Tests must verify that no tail channel retains data
from a previous longer frame.

The retransmitter callback handoff must be treated as a synchronized operation:
the pinned `DMXUART` library copies every callback-complete frame into a
shared completed buffer before calling the application callback. The
retransmitter snapshots each callback-complete frame into private storage and
zero-fills its unused tail before the foreground handoff. This prevents a
short frame from being paired with stale data from a previous longer frame.

The live runner selects the source length with `--pattern short --slots N` or
the frame-unique changing pattern with `--pattern dynamic-short --slots N`.
Representative commands are:

```bash
# Fixed partial image: channels 1..N must match and N+1..512 must be zero.
python3 Host Software/wireless_dmx_daemon/tests/run_retransmitter_acceptance.py \
  --tx-port /dev/ttyUSB0 --mega-port /dev/ttyUSB1 --receiver-port /dev/ttyUSB2 \
  --pattern short --slots 236 --value 99 --seconds 20

# Frame-unique partial image: detects torn/mixed universes and tail retention.
python3 Host Software/wireless_dmx_daemon/tests/run_retransmitter_acceptance.py \
  --tx-port /dev/ttyUSB0 --mega-port /dev/ttyUSB1 --receiver-port /dev/ttyUSB2 \
  --pattern dynamic-short --slots 236 --value 99 --change-ms 100 --seconds 20 \
  --expected-rate-hz 20 --rate-tolerance-hz 2
```

The production-rate gate requires the measured diagnostic promotion rate to be
at least 18 Hz for a 20 Hz run. The runner also reports sequence gaps and the
maximum/p95 promotion gaps separately, so packet loss is not hidden by an
average rate. Repeat the frame-unique test at the fragment boundaries 25, 235,
236, 237, 255, 256, 257, 471, 472, 473, 511, and 512 slots. A passing run has
zero invalid/torn records, zero nonzero-tail violations, zero sequence
backtracks, zero CRC errors, and no unexpected source MACs.

### 3. Input interruption and recovery

Stop and restart the Mega DMX generator, then reset the re-transmitter. Confirm
the receiver holds the last complete universe during source loss and accepts a
new complete universe after recovery.

### 4. Management-only coexistence

Run the daemon in management-only mode against `/dev/ttyUSB0`. Confirm:

- telemetry discovery works;
- normal retransmitted DMX remains unchanged;
- fail-safe/output controls behave as documented;
- management transmitter absence does not stop normal retransmission;
- daemon/transmitter reconnect does not corrupt the normal universe.

The extended dynamic soak uses:

```bash
python3 Host Software/wireless_dmx_daemon/tests/run_retransmitter_acceptance.py \
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

## Extended retransmitter validation runner

The staged extended validator uses the Mega and diagnostic receiver directly,
resets the receiver before every case, requires exactly one capture
acknowledgement, and stops immediately on a setup/no-data failure. It does not
open `/dev/ttyUSB0`, so it cannot introduce a second normal-DMX authority.

From the repository root, the default command runs only the safe preflight:

```bash
python3 Host Software/wireless_dmx_daemon/tests/run_retransmitter_extended_validation.py
```

Run the phases separately as follows:

```bash
# Thirty-second 236-slot preflight, then thirty-second 512-slot preflight at the
# production 10 Hz retransmission target.
python3 Host Software/wireless_dmx_daemon/tests/run_retransmitter_extended_validation.py --preflight-only

# 24, 25, 100, 235, 236, 237, 255, 256, 257, 471, 472, 473, 511, 512.
python3 Host Software/wireless_dmx_daemon/tests/run_retransmitter_extended_validation.py --matrix-only

# Real source-length transitions, including 512->24 and 24->512.
python3 Host Software/wireless_dmx_daemon/tests/run_retransmitter_extended_validation.py --transitions-only

# 15-minute 512-slot, 10-minute 24-slot, and 10-minute 237-slot soaks.
python3 Host Software/wireless_dmx_daemon/tests/run_retransmitter_extended_validation.py --soaks

# Run the complete staged validation (approximately one hour).
python3 Host Software/wireless_dmx_daemon/tests/run_retransmitter_extended_validation.py --all
```

Use `--mega-port`, `--receiver-port`, and `--receiver-baud` to override the
documented `/dev/ttyUSB1`, `/dev/ttyUSB2`, and 460800 defaults. Each invocation
writes per-case JSON plus `summary.json` and `summary.md` under
`Host Software/wireless_dmx_daemon/runs/retransmitter-extended/<timestamp>/`.

The completed extended validation recorded 25/27 passing cases. Two failures were
Mega source-result/rate-reporting harness issues; they did not indicate invalid
reconstruction, and retransmission integrity passed. A fully green rerun requires
fixing the Mega result-line capture/source-rate checks rather than changing the
retransmitter acceptance criteria.

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