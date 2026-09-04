# Feature 11 Extended 20 Hz Acceptance Test

## Purpose

Verify the production 20 Hz operating mode for more than ten minutes while
collecting receiver telemetry. The test uses the Arduino Mega at `/dev/ttyUSB1`
to verify the receiver's wired DMX output.

## Run

```bash
python3 Testing/feature11/tools/run_20hz_telemetry_soak.py \
  --tx-port /dev/ttyUSB0 \
  --mega-port /dev/ttyUSB1 \
  --seconds 660 \
  --dmx-hz 20 \
  --telemetry-interval 15 \
  --run-dir Testing/feature11/runs/20hz-extended
```

The transmitter is opened at `115200 8N2`; the Mega USB monitor is opened at
`115200 8N1`. The run sends a stable full 512-slot ramp at 20 Hz so the Mega
can validate every physical DMX frame, and requests telemetry every 15 seconds.

## Telemetry logging

The runner logs decoded binary telemetry events to `telemetry.jsonl`. The
transmitter's `TRANSMITTER_TELEMETRY_LOGGING` build option is intentionally not
enabled: it writes human-readable text on the same UART used for ENTTEC input
and would corrupt the DMX stream. Host-side binary logging is the deployment-
safe telemetry logging mode.

## Acceptance criteria

* Run duration is at least 601 seconds.
* At least 95% of scheduled DMX input frames are submitted.
* The Mega reports zero DMX pattern failures.
* The Mega reports nonzero complete DMX checks and the requested duration.
* Every telemetry request receives a complete valid report.
* Every report contains at least one receiver record.
* No telemetry framing or CRC errors occur.

## Recorded result

The acceptance run completed successfully on 2026-09-04 using transmitter
`/dev/ttyUSB0`, Mega monitor `/dev/ttyUSB1`, and two active receivers:

* 660-second requested run; Mega reported 659 seconds due to integer-second
  result rounding.
* 13,200/13,200 DMX input frames submitted at exactly 20.0 Hz.
* Mean DMX input interval: 50.0005 ms.
* Maximum DMX input interval: 61.62 ms.
* Mega checks: 29,290; passes: 29,290; failures: 0.
* Mega `no_data`: 8 ms.
* Telemetry requests: 43; complete reports: 43; success: 100%.
* Telemetry records: 2 per report; no framing or CRC errors.
* Mean telemetry latency: 55.23 ms; maximum: 55.58 ms.

Raw decoded telemetry is retained in
`Testing/feature11/runs/20hz-extended/telemetry.jsonl`, with the summary in
`Testing/feature11/runs/20hz-extended/manifest.json`.