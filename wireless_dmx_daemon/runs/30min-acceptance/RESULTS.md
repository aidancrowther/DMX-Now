# 30-Minute End-to-End Acceptance Results

**Date:** 2026-09-04  
**Result:** PASS

## Hardware and configuration

| Component | Configuration |
|---|---|
| Host daemon | Linux host implementation |
| Transmitter | `/dev/ttyUSB0`, 115200 8N2 |
| Arduino Mega monitor | `/dev/ttyUSB1`, 115200 8N1 |
| DMX input | Full 512-slot ENTTEC universe at 20 Hz |
| Pacer | Enabled, latest-state, 20 Hz |
| Telemetry | Enabled, request interval 15 seconds |
| Receivers | 2 active ESP8266 receivers |
| Duration | 1,800 seconds |

## Results

* 36,000 full-universe DMX frames submitted through the daemon PTY.
* Effective daemon input rate: 20.0 Hz.
* Mean DMX input interval: 49.9997 ms.
* Maximum DMX input interval: 65.93 ms.
* Daemon valid DMX frames: 36,000.
* Daemon submitted frames: 36,000.
* Daemon pacer drops: 0.
* Two receiver records remained visible throughout the run.
* Mega checks: 79,880.
* Mega passes: 79,880.
* Mega failures: 0.
* Mega reported no-data time: 19 ms.
* Transmitter and virtual client remained connected throughout.

## Acceptance decision

The daemon meets the substantial-completion target for the tested deployment
mode. The complete PTY-to-ENTTEC-parser-to-pacer-to-transmitter path operated at
20 Hz for 30 minutes, and the Arduino Mega observed no incorrect physical DMX
frames.

## Evidence

* `manifest.json` — machine-readable final result.
* `progress.jsonl` — 30-second daemon health/statistics checkpoints.
* `daemon_telemetry.jsonl` — receiver telemetry snapshots captured during the
  run.
* `../tests/run_30min_acceptance.py` — reproducible acceptance runner.

This result validates the tested 20 Hz production mode. It does not validate
experimental rates above 20 Hz or transmitter disconnect/reconnect behavior
under hardware fault injection.