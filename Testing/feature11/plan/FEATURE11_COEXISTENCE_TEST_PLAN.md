# Feature 11 DMX/Telemetry Coexistence Test

## Purpose

Measure whether occasional receiver-telemetry requests interfere with the
transmitter's ENTTEC DMX input while a receiver is operating.

## Run

The default run lasts three minutes, writes full 512-channel DMX frames at
10 Hz, and requests telemetry every 10 seconds:

```bash
python3 Testing/feature11/tools/test_dmx_telemetry_coexistence.py \
  --tx-port /dev/ttyUSB0 \
  --seconds 180 \
  --out Testing/feature11/coexistence-3min.json
```

The transmitter is opened at `115200 8N2`. The test does not flash either board
and does not require a Mega DMX monitor. A powered receiver must be listening
on the configured ESP-NOW channel so the report contains at least one record.

## Measurements

The result includes:

* Number and effective rate of DMX frames written to the transmitter.
* Mean and maximum interval between DMX writes.
* Number of telemetry requests.
* Number of complete multipart reports received.
* Telemetry response latency.
* Number of receiver records reported.
* CRC/framing/parser errors.

The test passes only if every request receives a complete valid report with at
least one receiver, no malformed responses occur, and at least 95% of the
requested DMX writes are submitted.

This transmitter-side test confirms serial coexistence and report handling. A
separate run with the existing Mega DMX monitor can measure receiver-delivered
universes and RF loss at the same time.

## Recorded result

The 60-second run using `/dev/ttyUSB0`, 10 Hz DMX, and telemetry requests every
10 seconds completed successfully:

* 600/600 DMX frames submitted (10.0 Hz effective rate)
* 6/6 complete telemetry reports received (100%)
* Two receiver records present in each report
* Mean telemetry latency: approximately 108 ms
* Maximum telemetry latency: approximately 111 ms
* No malformed management responses