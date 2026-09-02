# Feature 7 Automated Refresh-Rate Test Plan

## Purpose

Measure the highest practical wireless refresh rate through the integrated
receiver without allowing monitor reporting output to perturb DMX reception.
The MEGA uses `DMXSerial.packetReady()` and the Pico uses PIO/DMA capture as
their complete DMX-frame boundaries; both remain silent during recording.

## Hardware and safety

| Device | Port | Automated action |
|---|---|---|
| ESP-01 TX test sketch | `/dev/ttyUSB0` | compile and flash for each rate |
| Arduino MEGA monitor | `/dev/ttyUSB1` | flash only with `--flash-monitor` |
| Raspberry Pi Pico monitor | `/dev/ttyACM0` | optional replacement monitor; flash only with `--flash-monitor` |
| Integrated ESP-01 receiver | not connected | never flashed or modified |

The runner refuses missing ports and stores all new logs under
`Testing/feature7/runs/<UTC timestamp>/`. Historical captures remain in
`Testing/Feature 7 Tests (Old)/`.

## Low-interference monitor protocol

```text
host -> START <settle_seconds> <measure_seconds>\n
MEGA: silent during settle and measurement
MEGA -> RESULT seconds=... updates=... rate=... lost=... gaps=... loss=...%
              pat_err=... max_gap=... last_seq8=... no_data=...ms
```

The MEGA receives DMX in the DMXSerial UART ISR. Foreground work is only done
after `packetReady()`. The monitor uses the test transmitter's channel-1
sequence byte to filter identical physical retransmissions, while
`packetReady()` remains the authoritative complete-frame boundary. Channel 1
is not used to detect partial frames; it is used only to identify whether a
completed payload is the same wireless universe and to calculate sequence gaps.
The known deterministic pattern check remains a separate diagnostic. No USB
output occurs during the measured interval.

A two-part full-frame hash identity was experimentally evaluated as an
alternative. Although logically independent of channel 1, its approximately
22,500 byte operations/second foreground workload caused a large increase in
pattern errors on the single-buffer AVR monitor during the 10 Hz smoke test.
It was therefore rejected: the lightweight channel-1 filter produced the
lower-interference measurement path. `DmxSniff` is also unsuitable because it
uses `dataUpdated()`, which can fire for individual changed channel bytes.

## Sweep

Default rates: `5,10,15,20,22,25,27,30,32,35,37,40 Hz`.
Default timing: 10 seconds settle, 60 seconds record per point.

Run after verifying the receiver and wiring are powered and stable:

```bash
python3 Testing/feature7/tools/run_sweep.py --flash-monitor
```

To perform a compile-only monitor check first:

```bash
./flash_dmx_monitor.sh
```

Use `--continue-on-error` to collect later points after a failed flash or
capture. Use `--rates 10,20,30 --seconds 120` for a shorter/longer confirmation.

The Pico monitor can run the same sweep using its native USB telemetry and
PIO/DMA DMX input on GPIO 1. Connect the Pico ground to the DMX source ground
before treating any capture as valid:

```bash
python3 Testing/feature7/tools/run_sweep.py \
  --monitor-type pico --monitor-port /dev/ttyACM0 --flash-monitor
```

The Pico emits the same `RESULT` schema as the MEGA. Its metrics are directly
comparable, but a separate run directory must be used because the two monitors
have different frame-boundary implementations.

## Acceptance criteria

For each point, record:

* delivered rate (`updates / measured seconds`);
* sequence loss percentage and number of gaps;
* pattern errors;
* maximum inter-update gap;
* whether delivered rate tracks the requested rate.

Classify a point **reliable** when loss is at most 5%, pattern errors are zero,
and there is no sustained multi-period outage. The reliable ceiling is the
highest reliable requested rate. Report the highest delivered rate separately,
because a requested rate can exceed the transport's sustainable rate.

## Analysis commands

```bash
python3 Testing/feature7/tools/analyze.py Testing/feature7/runs/<run>
python3 Testing/feature7/tools/analyze.py --json Testing/feature7/runs/<run>
```

Every run contains `manifest.json` with ports, rates, timing, defines, flash
status, and capture status. No receiver-side change is part of this plan. If
clean runs indicate receiver queue loss, stop and obtain approval before
changing `receiver/receiver.ino` or receiver libraries.