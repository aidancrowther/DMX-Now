# Pico retransmitter acceptance mapping

The Pico replaces the Mega generator while the three ESP-01S assignments remain
fixed. This document maps the retained test plans to the finite runners
and identifies coverage they do not yet implement. The project and libraries
are present; missing firmware is no longer a blocker.

The 10 Hz physical-retransmitter baseline and 20 Hz daemon-transmitter target
are intentional. The current objective is to qualify the physical retransmitter
at 20 Hz. Qualification requires the complete applicable matrix at its original
durations, with wireless retransmitter diagnostics disabled, and at least 18 promotions per second
when the physical source runs at 20 Hz or faster. A successful short preflight
or 10 Hz baseline does not satisfy that objective.

## Procedure and fixed roles

Use the sibling [bench procedure](../../test-harness/README.md) for toolchain,
Pico installation, exact build/flash commands, wiring, and command syntax.
[`devices.json`](../../espdmx/testing/devices.json) owns persistent assignments:

| Role | USB identity | ESP ROM MAC | Required mode |
|---|---|---|---|
| `diagnostic-receiver` | CH340 `1a86:7523`, location `2-1.2` | `2c:f4:32:76:24:ff` | DMX output disabled; streamed `RDX1` universes or silent `RDS1` summaries on `460800 8N1`. |
| `management-transmitter` | CH340 `1a86:7523`, location `2-1.3` | `2c:f4:32:36:35:75` | `TRANSMITTER_LOCK_MANAGEMENT_ONLY`; binary management on `115200 8N2`. |
| `retransmitter` | FTDI `0403:6001`, serial `A602ZBFL` | `84:cc:a8:95:8e:ca` | Sole normal-DMX source; flash/control only through the Pico MUX and boot/reset wiring. |
| `pico-controller` | Native `2e8a:000a`, UID `503359278A634D9F` | Not applicable | PIO/DMA DMX source and boot/reset/MUX controller. |

The Pico UID is unchanged from the former CircuitPython `239a:80f4` device.
The two CH340 adapters have no serial numbers and remain on their recorded USB
locations. `bench.py` resolves USB identity, validates the image role and hash,
and verifies the ROM MAC on the same connection used to flash. All roles use
ESP-NOW channel 1 and universe 1. No enumerated port is a role selector.

Production extended qualification requires `RETRANSMITTER_DIAGNOSTICS=0` and
`RETRANSMITTER_DIAGNOSTIC_BROADCAST=0` throughout the entire suite. Both build
and runner use `--wireless-diagnostics off` by default. The runner verifies
the installed `20hz-diagnostics-off` profile. The on profile is a separate
diagnostic comparison using `20hz-diagnostics-on`, never a substitute for the
off-profile qualification. Silent receiver summaries remain allowed and must
report `txdiag == 0` for off or `txdiag > 0` for on. This directly tests the
reported diagnostics-dependent failure near 19 Hz rather than preserving
wireless diagnostics as a workaround.

The normal ESPDMX packet layout remains unchanged: one 512-channel universe is
three fragments of 236, 236, and 40 bytes. Partial physical universes zero-fill
through channel 512. `management-transmitter` sends telemetry/control and
explicit priority traffic only. The content runner currently sends no priority
traffic, so an unexpected priority record fails its normal-content cases.

## Source documents and implemented phases

The complete documentation review is in
[documentation-audit.md](../../test-harness/documentation-audit.md). The
[20 Hz branch review](../../test-harness/20hz-branch-review.md) records the
additional long/growing cases and defects in the prior experiment.

| Source requirement | Runner phase | Mapping |
|---|---|---|
| E2E wired constants, ramps, boundary values, and 236-slot examples | `baseline` | Seven concrete constants, wraparound ramp, fixed 236-slot and frame-unique 236-slot examples. |
| E2E extended preflight | `preflight` | 236 and 512 slots, 30 seconds each. |
| E2E partial and fragment boundaries | `matrix` | All 14 retained lengths, 30 seconds each. |
| E2E real source-length transitions | `transitions` | All eight directed pairs. Establish the first length, change the source live, and measure the destination without resetting the receiver between lengths. |
| Historical Feature 7 rate list | `rates` | All 15 retained rates as physical Pico input rates, 10 seconds settling and 60 seconds measurement. This is not the original physical-output/wireless-rate experiment. |
| E2E extended soaks | `soaks` | 512 slots for 900 seconds; 24 and 237 slots for 600 seconds each. |
| E2E management coexistence | `coexistence` | 900 seconds, full universe, epoch changes every 1000 ms, telemetry polling every 10 seconds. |
| Experimental branch long matrix | `long` | All 18 lengths for 300 seconds each. Adds 200, 300, 400, and 500 slots to the original boundary set. |
| Experimental branch growing source | `growing` | Original 60-second limited-growth case and 520-second complete 24-through-512 traversal. |

From the parent `DMX` directory, every listed case is individually reproducible:

```bash
python3 test-harness/run_matrix.py --case CASE_ID --target-rate 20
python3 test-harness/run_matrix.py --phase extended --target-rate 20 --wireless-diagnostics off --output test-harness/results/pico-migration/qualification-extended-diagnostics-off-v2
python3 test-harness/run_matrix.py --phase long --target-rate 20
python3 test-harness/run_matrix.py --phase growing --target-rate 20
python3 test-harness/run_matrix.py --phase all --target-rate 20 --output test-harness/results/pico-migration/new-qualification
```

The exact catalog is [`matrix.json`](../../test-harness/matrix.json), generated
from `run_matrix.py` by `--phase all --list`. The 73 cases contain 10880 seconds
of measurement and 318 seconds of prescribed settling, plus reset/baseline
setup. A full run takes about 3.15 hours. The 18 long cases alone measure for
90 minutes. None of these windows can be shortened while retaining the same
acceptance claim.

`--phase extended` selects 46 of those cases: the two preflights, 14 boundaries,
eight transitions, three soaks, coexistence, and 18 long-matrix cases. It
supports a silent receiver and preserves 9120 seconds of measurement. The
baseline, source-rate, and growing families remain separate catalog coverage.
The full catalog requires streamed mode because the current silent validator
does not support constants, ramps, or the growing pattern.

## Stimulus and execution semantics

Each independent case resets `diagnostic-receiver`, selects the source pattern
and physical timing, waits for its prescribed settling period, and opens a
strict measurement window. The runner verifies the Pico UID and installed role
manifests. It runs one management-only service throughout a phase, samples its
state every second, and requests management telemetry every 10 seconds.

For a transition, it first requires a matching five-second stream at
`from_slots`, then changes the Pico configuration without stopping the source.
DMA buffers apply that update to a later complete frame. The receiver remains
running between the two lengths. The fixed short example first establishes a
nonzero full-length universe to expose retained tail values.

All default physical frames use `TIMING 22700 90 22 0`. Period, BREAK, and MAB
are microseconds; the last argument is the start code. A slot is 44 microseconds
at 250000 8N2. The Pico timing fit rule is
`period >= BREAK + MAB + 44*(slots+1) + 4`. A full default frame requires
22688 microseconds and fits the approximately 44.0529 Hz source cadence.
Source-rate cases change only the period to `round(1000000/rate)`.

Pattern names in the case table map to these Pico commands:

| Pattern | Command and expected complete universe |
|---|---|
| `const` | `GENERATE CONST base`; all 512 values equal base. |
| `ramp` | `GENERATE RAMP base`; channel `c` equals `(base+c-1)&255`. |
| `short` | `GENERATE SHORT slots base`; the same ramp through slots, then zeros. |
| `dynamic` | `GENERATE DYNAMIC_SHORT slots base 100`; channel 1 is a frame-unique epoch. Channel `c>=2` is `(base+epoch*29+c*37+(c>>3)*11)&255`. Tail values are zero. The legacy interval parameter does not slow this pattern. |
| `interval` | `GENERATE INTERVAL slots base 1000`; the same epoch formula, changing once per 1000 ms of generated source time. |
| `growing` | `GENERATE GROWING 24 512 1000 base`; add one slot per second, channel 1 is epoch, channels 2/3 encode length in little-endian order, other channels use the dynamic formula, and the tail is zero. |

The 60-second growing case covers only the beginning of the range. The
520-second case requires observing every length 24 through 512. A complete
traversal needs 488 seconds before its terminal observation window.

## Per-case verdict and evidence

Each case writes `<case-id>.json`, `<case-id>.receiver.bin`, and
`<case-id>.management-transmitter.jsonl`, with an aggregate `summary.json`.
The case JSON contains Pico setup commands, source counters, measured duration,
promotion rate, source MACs, mismatch details, CRC counts, sequence gaps, host
arrival-gap statistics, telemetry report counts, and named Boolean checks.
Image hashes and the runner hash accompany the summary. In silent mode the raw
receiver file contains serial text captured during measurement and the case
JSON contains the parsed `RDS1` summary. `RDS1` is not an `RDX1` CRC-protected
record stream.

The streamed checks require:

- Positive source frames and diagnostic promotions, with zero PIO underflows
  and late-DMA events.
- Source rate within the larger of 0.05 Hz or 0.5 percent of the requested
  physical cadence.
- At target 20 Hz with source at least 20 Hz, promotion rate at least 18 Hz.
  For slower input, the rate floor is 90 percent of the source rate. A 10 Hz
  baseline uses a separate 9 Hz floor. Promotion rate also must not exceed
  110 percent of the smaller source/target rate plus one frame per window.
- Exact content for all 512 channels, zero retained tail values, only the
  assigned retransmitter source MAC, and no sequence duplicate/backtrack.
- Zero diagnostic CRC errors and unknown/unexpected record types in the
  strict window.
- Connected, synchronized management-only mode throughout each sample;
  progressing telemetry reports and receiver telemetry sequence; no reported
  consecutive telemetry failures or management transport error; and the
  assigned receiver MAC present.

Silent extended cases validate source MAC, full pattern/tail content,
promotion order, and counts inside the diagnostic receiver. The runner
requires every promotion to match, zero corrupt promotions, `txdiag == 0` for
the production off profile or `txdiag > 0` for the on comparison, all three fragment counts
positive, fragment imbalance no greater than the larger of 10 packets or
10 percent, and zero QuickESPNow queue evictions/push failures and receiver
ring overflows. Management and Pico timing gates remain active in silent mode.
Host `RDX1` CRC and host-arrival-gap checks apply only to streamed captures.

Source, promotion, and content checks apply separately. Maximum/p95 host
arrival gaps and wireless sequence gaps are recorded, but streamed mode does
not currently enforce a loss threshold, receiver queue counters, or fragment
balance. Host arrival timing includes UART/USB buffering and is not a direct
measurement of RF packet timing. These limits matter when comparing the result
with the older Feature 7 and silent-capture criteria.

`passed` means the implemented checks for that case passed. `failed` retains
every failed check. `could-not-run` includes an exception reason or "Not
executed yet". The runner stops after setup/no-data failure and preserves
unexecuted cases. `phase_passed` covers the selected phase only.
`complete_validation` remains false because the additional requirements below
are not all represented by these 73 cases.

## Remaining acceptance coverage

| Requirement | Current status and missing evidence |
|---|---|
| Feature 6 dropped middle/final, duplicate, reordered, corrupt, stale, malformed, midstream, reset/rebaseline, and rollover cases | The separate 11-case RF runner is prepared, pending hardware proof. It uses only the assigned retransmitter for injection and verifies retained last-good state and recovery without a receiver reboot. See the exact mapping below. |
| Feature 6 two-receiver case | Cannot run with only the three fixed roles. Requires another receiver. |
| Original silent-capture fragment balance and zero receiver queue/ring failures | Implemented in silent `extended` mode, with `txdiag == 0` for production off or `txdiag > 0` for the on comparison. Must still pass in the actual run. Streamed captures do not supply these counters. |
| Feature 7 original wireless-rate/physical-output sweep | The `rates` phase varies physical source cadence while retaining a 20 Hz retransmitter target. It does not establish the original at-most-5-percent loss criterion across configurable wireless rates or measure physical receiver DMX. |
| Source interruption, retransmitter reset, receiver disappearance, management absence/reconnect, and daemon restart | Compatibility cases are prepared, pending hardware proof. Receiver disappearance uses a 20-second reset hold, not a physical unplug. |
| Priority, gate metadata, locked/open-channel behavior, ACK/retry behavior, unlock, and normal resumption | Compatibility cases are prepared for 10 and 20 priority events, all expected-receiver first-attempt ACKs, six boundary-channel locks, unlock, and normal resumption. Pending hardware proof. This does not cover every historical Feature 8 subcase. |
| Runtime transmitter mode and static-lock rejection | The management-only bridge-request rejection case is prepared, pending hardware proof. Runtime-capable mode and locked-bridge rejection remain separate tests; never operate two normal authorities. |
| Fail-safe hold/blackout/disable-line and output/locate controls | Four compatibility cases cover logical fail-safe configuration, activation, and fresh-input recovery, pending hardware proof. The diagnostic receiver disables physical output and locator GPIO behavior. A production receiver and physical monitor are needed for the original physical claims. |
| Observed-universe display and hard-lock preservation | The compatibility runner validates multipart observed-universe content and progression in normal windows, including locked values in the hard-gate case. The dedicated 30-second `management-observation` case is prepared, pending hardware proof. Dashboard display and remaining historical subcases are not validated by these data checks. |
| Below-24-slot rejection, nonzero start code, malformed BREAK/MAB, and intentional gap boundaries | Compatibility cases cover 0/1/23 slots, start codes 1/255, minimum valid and long-BREAK timing, and invalid Pico commands, pending hardware proof. Command rejection does not exercise malformed on-wire timing. Remaining gap boundaries still need stimulus and evidence. |
| Independent waveform and electrical checks | No independent waveform instrument is part of this run. PIO counters do not prove actual BREAK/MAB, signal levels, RS-485 polarity/termination quality, or receiver physical DMX output. |
| Historical Feature 8/11/12 detailed subcases | The retained summaries name past results, but several original `Testing/` plans and raw runs are absent. Unnamed subcases cannot be claimed covered from those summaries. |
| Battery comparator/low-battery timing and production PCB/antenna behavior | Requires the corresponding battery and production hardware. Bench ESP-01S UART wiring does not validate these physical components. |

The [audit](../../test-harness/documentation-audit.md) retains exact historical
timings and criteria for these cases. Missing coverage is not waived by a
successful implemented phase.

## Preliminary results and stopped run

The original 10 Hz scheduler passed 30-second preflights at 9.97 Hz for
236 slots and 10.00 Hz for 512 slots. Building that scheduler for 20 Hz produced
15.30 Hz at 512 slots and failed the 18 Hz gate. Continuous RX with an immutable
TX snapshot, a fresh-input requirement, and absolute-deadline rebasing produced
19.62 Hz at 236 slots and 19.41 Hz at 512 slots in subsequent 30-second
preflights. These observations are preliminary and used the production
wireless-diagnostics-off setting. They do not prove the full extended suite.

The initial 73-case streamed run was interrupted during the diagnostic
investigation. Its
[partial report](../../test-harness/results/pico-migration/qualification-stream/summary.json)
is retained as an incomplete comparison, not an invalid off-profile run under
the final requirement. It must not be labeled full qualification. The complete
production off-profile run must retain the 5-, 10-, and 15-minute cases and all other prescribed
windows. The first
[extended attempt](../../test-harness/results/pico-migration/qualification-extended-diagnostics-off/summary.json)
could not run its first case because of
`SerialException: read failed: [Errno 6] Device not configured`.
The current
[extended rerun](../../test-harness/results/pico-migration/qualification-extended-diagnostics-off-v2/summary.json)
is pending a complete verdict. No result is presumed from a directory name or
scheduled case. The 23 compatibility cases and 11 Feature 6 cases below are
prepared but have not yet run on hardware. The
[status page](../../espdmx/testing/README.md) links the preliminary
reports and software checks.

The host suite initially failed one macOS path-alias assertion, then passed all
132 tests after the fix. Ten role-identity tests passed. Those software results
do not establish any missing hardware case.

## Exact implemented case table

The table below mirrors `matrix.json`. A transition's starting length is a
five-second validated baseline before its listed destination measurement.
Every row uses BREAK 90 microseconds, MAB 22 microseconds, and start code zero.
The `--case` command above executes the exact ID without shortening its window.

| Case ID | Pattern/base | Physical slots | Period, microseconds | Settle, seconds | Measure, seconds |
|---|---|---|---:|---:|---:|
| `constant-0` | const, 0 | 512 | 22700 | 3 | 30 |
| `constant-1` | const, 1 | 512 | 22700 | 3 | 30 |
| `constant-77` | const, 77 | 512 | 22700 | 3 | 30 |
| `constant-127` | const, 127 | 512 | 22700 | 3 | 30 |
| `constant-128` | const, 128 | 512 | 22700 | 3 | 30 |
| `constant-254` | const, 254 | 512 | 22700 | 3 | 30 |
| `constant-255` | const, 255 | 512 | 22700 | 3 | 30 |
| `ramp-255` | ramp, 255 | 512 | 22700 | 3 | 30 |
| `example-236-short` | short, 99 | 236 | 22700 | 3 | 20 |
| `example-236-dynamic` | dynamic, 99 | 236 | 22700 | 3 | 20 |
| `preflight-236` | dynamic, 53 | 236 | 22700 | 3 | 30 |
| `preflight-512` | dynamic, 53 | 512 | 22700 | 3 | 30 |
| `boundary-24` | dynamic, 53 | 24 | 22700 | 3 | 30 |
| `boundary-25` | dynamic, 53 | 25 | 22700 | 3 | 30 |
| `boundary-100` | dynamic, 53 | 100 | 22700 | 3 | 30 |
| `boundary-235` | dynamic, 53 | 235 | 22700 | 3 | 30 |
| `boundary-236` | dynamic, 53 | 236 | 22700 | 3 | 30 |
| `boundary-237` | dynamic, 53 | 237 | 22700 | 3 | 30 |
| `boundary-255` | dynamic, 53 | 255 | 22700 | 3 | 30 |
| `boundary-256` | dynamic, 53 | 256 | 22700 | 3 | 30 |
| `boundary-257` | dynamic, 53 | 257 | 22700 | 3 | 30 |
| `boundary-471` | dynamic, 53 | 471 | 22700 | 3 | 30 |
| `boundary-472` | dynamic, 53 | 472 | 22700 | 3 | 30 |
| `boundary-473` | dynamic, 53 | 473 | 22700 | 3 | 30 |
| `boundary-511` | dynamic, 53 | 511 | 22700 | 3 | 30 |
| `boundary-512` | dynamic, 53 | 512 | 22700 | 3 | 30 |
| `transition-512-24` | dynamic, 53 | 512 to 24 | 22700 | 3 | 30 |
| `transition-24-512` | dynamic, 53 | 24 to 512 | 22700 | 3 | 30 |
| `transition-512-236` | dynamic, 53 | 512 to 236 | 22700 | 3 | 30 |
| `transition-236-512` | dynamic, 53 | 236 to 512 | 22700 | 3 | 30 |
| `transition-473-471` | dynamic, 53 | 473 to 471 | 22700 | 3 | 30 |
| `transition-471-473` | dynamic, 53 | 471 to 473 | 22700 | 3 | 30 |
| `transition-257-255` | dynamic, 53 | 257 to 255 | 22700 | 3 | 30 |
| `transition-255-257` | dynamic, 53 | 255 to 257 | 22700 | 3 | 30 |
| `source-rate-1` | dynamic, 53 | 512 | 1000000 | 10 | 60 |
| `source-rate-2` | dynamic, 53 | 512 | 500000 | 10 | 60 |
| `source-rate-3` | dynamic, 53 | 512 | 333333 | 10 | 60 |
| `source-rate-5` | dynamic, 53 | 512 | 200000 | 10 | 60 |
| `source-rate-10` | dynamic, 53 | 512 | 100000 | 10 | 60 |
| `source-rate-15` | dynamic, 53 | 512 | 66667 | 10 | 60 |
| `source-rate-20` | dynamic, 53 | 512 | 50000 | 10 | 60 |
| `source-rate-22` | dynamic, 53 | 512 | 45455 | 10 | 60 |
| `source-rate-25` | dynamic, 53 | 512 | 40000 | 10 | 60 |
| `source-rate-27` | dynamic, 53 | 512 | 37037 | 10 | 60 |
| `source-rate-30` | dynamic, 53 | 512 | 33333 | 10 | 60 |
| `source-rate-32` | dynamic, 53 | 512 | 31250 | 10 | 60 |
| `source-rate-35` | dynamic, 53 | 512 | 28571 | 10 | 60 |
| `source-rate-37` | dynamic, 53 | 512 | 27027 | 10 | 60 |
| `source-rate-40` | dynamic, 53 | 512 | 25000 | 10 | 60 |
| `soak-512` | dynamic, 53 | 512 | 22700 | 3 | 900 |
| `soak-24` | dynamic, 53 | 24 | 22700 | 3 | 600 |
| `soak-237` | dynamic, 53 | 237 | 22700 | 3 | 600 |
| `coexistence-900` | interval, 53 | 512 | 22700 | 3 | 900 |
| `long-24` | dynamic, 53 | 24 | 22700 | 3 | 300 |
| `long-25` | dynamic, 53 | 25 | 22700 | 3 | 300 |
| `long-100` | dynamic, 53 | 100 | 22700 | 3 | 300 |
| `long-200` | dynamic, 53 | 200 | 22700 | 3 | 300 |
| `long-235` | dynamic, 53 | 235 | 22700 | 3 | 300 |
| `long-236` | dynamic, 53 | 236 | 22700 | 3 | 300 |
| `long-237` | dynamic, 53 | 237 | 22700 | 3 | 300 |
| `long-255` | dynamic, 53 | 255 | 22700 | 3 | 300 |
| `long-256` | dynamic, 53 | 256 | 22700 | 3 | 300 |
| `long-257` | dynamic, 53 | 257 | 22700 | 3 | 300 |
| `long-300` | dynamic, 53 | 300 | 22700 | 3 | 300 |
| `long-400` | dynamic, 53 | 400 | 22700 | 3 | 300 |
| `long-471` | dynamic, 53 | 471 | 22700 | 3 | 300 |
| `long-472` | dynamic, 53 | 472 | 22700 | 3 | 300 |
| `long-473` | dynamic, 53 | 473 | 22700 | 3 | 300 |
| `long-500` | dynamic, 53 | 500 | 22700 | 3 | 300 |
| `long-511` | dynamic, 53 | 511 | 22700 | 3 | 300 |
| `long-512` | dynamic, 53 | 512 | 22700 | 3 | 300 |
| `growing-60` | growing, 53 | 24 through 512 | 22700 | 0 | 60 |
| `growing-full` | growing, 53 | 24 through 512 | 22700 | 0 | 520 |

## Compatibility and recovery case mapping

[`run_compatibility.py`](../../test-harness/run_compatibility.py) adds these
23 cases to the original 73-case catalog. Every row is pending because hardware
execution has not yet occurred. The runner's case reports replace that pending
state with `passed`, `failed`, or `could-not-run` and retain the reason.

The runner requires the streamed diagnostic receiver, the production
`20hz-diagnostics-off` retransmitter, and the locked management transmitter.
Each case stops the Pico, resets the receiver for 0.1 seconds, allows two
seconds for boot, and rediscovers synchronized management telemetry within
35 seconds. The initial source is `GENERATE DYNAMIC_SHORT 512 53 100` with
`TIMING 22700 90 22 0`. It settles for three seconds and must pass a 10-second
baseline at 18 or more normal promotions per second.

Every measurement window checks diagnostic CRCs, known record types, source
MACs, and the supplied content pattern. Normal data must come from
`retransmitter`; priority data must come from `management-transmitter`.
Strict normal windows also require positive promotions, sequence order, and
their listed rate floor. Management samples must remain connected,
synchronized, management-only, and free of transport and consecutive telemetry
errors, except during intentional management absence. Pure normal windows also
require matching daemon observed-universe content; windows of at least
10 seconds require its multipart update count to progress. Each case requires
telemetry reports to progress. A fresh source uses base 99 and another
three-second settling window unless the row says otherwise.

Each priority event sends all 512 values as `99 + index % 100`, repeated three
times with a five-second TTL, then captures for 10 seconds. The event must
finish with the assigned receiver in both the expected and first-attempt ACK
sets, no retries, and a matching priority diagnostic record. Ordinary priority
windows also validate continuing normal content.

| Case ID | Pico stimulus or interruption | Measurement and required result | Status |
|---|---|---|---|
| `below-minimum-0` | Change the source to zero data slots. | Drain one second; require no normal promotion for 20 seconds. Restore fresh valid data and require 20 seconds at least 18 Hz. | Pending |
| `below-minimum-1` | Change the source to one data slot. | Same rejection and recovery windows as `below-minimum-0`. | Pending |
| `below-minimum-23` | Change the source to 23 data slots. | Same rejection and recovery windows as `below-minimum-0`. | Pending |
| `start-code-1` | Keep 512 slots and set start code 1. | Drain one second; require no normal promotion for 20 seconds. Restore start code zero with fresh data and require 20 seconds at least 18 Hz. | Pending |
| `start-code-255` | Keep 512 slots and set start code 255. | Same rejection and recovery windows as `start-code-1`. | Pending |
| `timing-minimum` | `TIMING 22672 88 8 0`, 512 dynamic slots. | Settle three seconds; measure 30 seconds at least 18 Hz with exact content. | Pending |
| `timing-long-break` | `TIMING 100000 880 12 0`, 512 dynamic slots at 10 Hz. | Settle three seconds; measure 30 seconds at least 9 Hz with exact content. | Pending |
| `timing-rejections` | Send the five invalid commands listed below while the normal source runs. | Each command must return `ERROR`; unchanged normal data must pass 30 seconds at least 18 Hz. | Pending |
| `source-stop-resume` | Pico `STOP`, then restart fresh data. | Drain one second; require no normal promotion for 20 seconds, then recover for 20 seconds at least 18 Hz. | Pending |
| `retransmitter-reset` | Pico `RESET` while the physical source continues. | In a five-second recovery window, the first normal promotion must occur after at least 2.5 seconds. The next 20 seconds must pass at least 18 Hz. | Pending |
| `management-absence` | Stop the daemon and hold the assigned management device in reset for 30 seconds. | Normal data must remain at least 18 Hz during absence. Release reset, rediscover, pass 20 seconds at least 18 Hz, and complete one priority event. | Pending |
| `management-reset` | Pulse the management UART adapter's RESET for 0.1 seconds. | Normal data must pass 30 seconds at least 18 Hz; complete one priority event afterward. | Pending |
| `daemon-restart` | Stop the management service for 10 seconds, leaving its ESP running. | Normal data must remain at least 18 Hz. Restart and rediscover, pass 20 seconds at least 18 Hz, and complete one priority event. | Pending |
| `receiver-removal` | Hold the diagnostic receiver in reset for 20 seconds, then allow three seconds for boot. | Require no normal records during reset, 20 seconds of restored normal data at least 18 Hz, and one successful priority event. This simulates removal without unplugging USB. | Pending |
| `management-role-lock` | Stop the service and request bridge mode `0` on the assigned management UART. | Within five seconds, require mode `1` and `accepted=false`. Rediscover and pass 20 seconds at least 18 Hz. | Pending |
| `management-observation` | Keep the default 512-slot dynamic source active. | Measure 30 seconds at least 18 Hz and require matching multipart observed-universe content with a progressing update count. | Pending |
| `priority-10` | Send 10 priority events using the common event procedure. | Require all expected first-attempt ACKs and matching content for every 10-second event window. Settle three seconds, then verify eight seconds of normal data at least 18 Hz; invalid and unknown ACK counts must be zero. | Pending |
| `priority-20` | Send 20 priority events using the common event procedure. | Same criteria as `priority-10`, retaining all 20 event windows. | Pending |
| `hard-gates` | Lock channels 1, 236, 237, 472, 473, and 512; send priority value 99. Open all six and send priority value 100. | Each 10-second priority window requires a gate-applied ACK. Verify 20 seconds at least 18 Hz with locked values retained and other channels dynamic; after unlock, settle three seconds and verify 20 seconds at least 18 Hz with all channels dynamic. | Pending |
| `failsafe-hold-default` | Configure hold with a 60-second timeout, then Pico `STOP`. | Verify configuration for 20 seconds at least 18 Hz, drain one second, then observe 72 seconds with no normal data. Telemetry must show active fail-safe and exactly one activation. Fresh input must recover for 20 seconds at least 18 Hz and clear fail-safe. | Pending |
| `failsafe-hold` | Configure hold with a 30-second timeout, then Pico `STOP`. | Use the same configuration and recovery checks as `failsafe-hold-default`, with a 42-second absence window. | Pending |
| `failsafe-blackout` | Configure blackout with a 30-second timeout, then Pico `STOP`. | Same logical checks and windows as `failsafe-hold`; no physical blackout measurement. | Pending |
| `failsafe-disable-line` | Configure disable-line with a 30-second timeout, then Pico `STOP`. | Same logical checks and windows as `failsafe-hold`; no physical line-disable measurement. | Pending |

`timing-rejections` sends exactly these commands:

```text
TIMING 22000 90 22 0
TIMING 22700 1 22 0
TIMING 22700 90 7 0
TIMING 22700 90 22 256
GENERATE SHORT 513 53
```

This case proves generator command validation only. It does not transmit an
invalid BREAK or MAB. The hard-gate matcher infers the dynamic epoch from open
channel 2 because channel 1 is locked. Fail-safe telemetry must report the
requested mode, timeout, and configuration generation before interruption.
The receiver's physical DMX output remains disabled for every case.

From the parent `DMX` directory, the prepared commands are:

```bash
python3 test-harness/run_compatibility.py --list
python3 test-harness/run_compatibility.py --case priority-20 --output test-harness/results/pico-migration/priority-20-new-run
python3 test-harness/run_compatibility.py --output test-harness/results/pico-migration/compatibility-new-run
```

The runner writes `<case-id>.json` with all windows, telemetry samples,
commands, and named checks. Each window retains a separate raw receiver file.
The aggregate `summary.json` initializes unexecuted cases as `could-not-run`
with reason `Not executed yet`. The runner continues after a case failure.

## Feature 6 RF fault case mapping

[`run_feature6.py`](../../test-harness/run_feature6.py) preserves 11 RF cases
through the assigned `retransmitter`; no other ESP becomes a normal source.
The injector is `Tests/espnow_universe_tx`, built for `WIRELESS_REFRESH_HZ=20`.
It transmits the original Feature 6 pattern, `universe[i] = (i + sequence) & 255`.
The diagnostic receiver uses `RX_VALIDATE_TEST_PATTERN=1` and silent summaries
to check that deterministic pattern. This is a test oracle, and its integrity
rejection does not establish detection of arbitrary corrupted production data.
These cases are separate from the physical-input 20 Hz throughput qualification.

Every listed case is pending hardware execution. Each capture lasts 20 seconds
and has a 25-second host deadline. The runner holds the injector in the Pico's
`BOOTLOADER` mode until it has received exactly one capture ACK, then sends
`RUN`. A fresh capture resets the receiver for 0.1 seconds and allows two
seconds for boot. Management telemetry is sampled about once per second.

Every capture requires the assigned source MAC, zero receive-queue evictions,
queue push failures, and receiver ring overflows, and `txdiag == 0`.
Management must remain synchronized and connected in management-only mode,
with no transport or telemetry error, progressing reports, and more than one
receiver telemetry sequence. A successful-data case requires positive
promotions, every promotion matching, and zero corrupt promotions. Sequence
backtracks must be zero except for the deliberate reset case below.

The four negative cases first establish a 20-second known-good baseline. They
then use `CAPTURE CONTINUE` to reset measurement counters while preserving
active and staging state. After fault injection, the active universe must
still exist with the same sequence and checksum as the held baseline.
All seven fault-injection variants then receive another 20 seconds of valid
normal RF data without a receiver reboot. That recovery must satisfy the
normal-data and common management checks.

| Case ID | Injector setting and stimulus | Required result beyond common checks | Status |
|---|---|---|---|
| `normal` | No fault hook; full normal RF frames. | Positive matching promotions and zero sequence backtracks. | Pending |
| `drop-middle` | `TEST_DROP_FRAGMENT_INDEX=1`; omit the middle fragment of every frame. | Zero promotions, positive incomplete-or-timeout abandonment count, `rx1 == 0`, unchanged last-good universe, and valid recovery. | Pending |
| `drop-final` | `TEST_DROP_FRAGMENT_INDEX=2`; omit the final fragment of every frame. | Zero promotions, positive incomplete-or-timeout abandonment count, `rx2 == 0`, unchanged last-good universe, and valid recovery. | Pending |
| `duplicate` | `TEST_DUPLICATE_FRAGMENT_INDEX=1`; duplicate each middle fragment. | Positive matching promotions, positive duplicate-fragment count, and valid recovery. | Pending |
| `reorder` | `TEST_REORDER_FRAGMENTS`; send fragments in order 2, 0, 1. | Positive matching promotions despite reordered arrival, then valid recovery. | Pending |
| `stale` | `TEST_DELAYED_FRAGMENT`; inject a fragment after 2500 ms, beyond the 2000 ms staging timeout and before the 3000 ms reset threshold. | Positive matching promotions and stale-fragment count, zero reset rebaselines, then valid recovery. | Pending |
| `corrupt` | `TEST_CORRUPT_FRAGMENT_INDEX=1`, `TEST_CORRUPT_BYTE=0`; XOR the first middle-fragment payload byte with `0xff`. | Zero promotions, positive integrity-failure count, unchanged last-good universe, and valid recovery. | Pending |
| `malformed` | `TEST_MALFORMED_FRAGMENT`; the middle fragment declares offset 511 with a 236-byte payload. | Zero promotions, positive malformed count, unchanged last-good universe, and valid recovery. The bounds fault travels over RF; the original plan used a receiver startup hook. | Pending |
| `midstream` | `TEST_FORCE_SEQUENCE_START=100`. | First promoted sequence at least 100, followed by matching promotions. | Pending |
| `reset` | Normal injector image; Pico `RESET` seven seconds into capture. | Positive matching promotions, positive stale-fragment count, exactly one reset rebaseline, and exactly one sequence backtrack. | Pending |
| `wrap` | `TEST_SEQUENCE_WRAP`; start at `0xfffffffe`. | First sequence exactly `0xfffffffe`, exactly one wrap, zero wrap gaps, and zero reset rebaselines. | Pending |

The [bench procedure](../../test-harness/README.md#run-feature-6-rf-fault-cases)
contains the build commands for all variants. `reset` reuses the `normal`
image. Individual cases use their exact IDs:

```bash
python3 test-harness/run_feature6.py --list
python3 test-harness/run_feature6.py --case drop-middle --output test-harness/results/pico-migration/feature6-drop-middle-new-run
python3 test-harness/run_feature6.py --output test-harness/results/pico-migration/feature6-new-run
```

The runner saves installed production manifests before the first flash.
Its final cleanup restores `retransmitter` through the Pico and restores
`diagnostic-receiver` through its assigned UART. It sets
`production_images_restored: true` only after both succeed. Restoration itself
is pending hardware verification. The report contains each capture's raw
receiver transcript, parsed summary, active-state checksum/sequence,
management samples, commands, and checks. Unexecuted cases retain their
`could-not-run` reason. The two-receiver case still requires a fourth ESP.
