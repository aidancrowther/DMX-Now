# Feature 7 Results — Grounded Refresh-Rate Verification

**Date:** 2026-09-02  
**Authoritative Pico run:** `Testing/feature7/runs/20260902_154822/`  
**Pico smoke run:** `Testing/feature7/runs/20260902_154700/`  
**MEGA comparison run:** `Testing/feature7/runs/20260902_132200/`  
**Hardware:** ESP-NOW TX `/dev/ttyUSB0`; Pico monitor `/dev/ttyACM0`; MEGA comparison monitor `/dev/ttyUSB1`  
**Configuration:** `WIRELESS_TX_OVERHEAD_MS=27`, `WIRELESS_TX_DRAIN_TIMEOUT_MS=100`; 10 s settle + 60 s measurement per point  
**Receiver:** not flashed or modified

## Executive conclusion

With the Pico DMX input ground connected, the final PIO/DMA monitor completed a
valid full sweep. The highest requested setting meeting the acceptance rule was
**20 Hz** on the Pico run: **19.67 Hz delivered**, **0.50% inferred sequence
loss**, and **zero pattern errors**.

The **22 Hz boundary requires caution**. The Pico run produced 76 pattern errors
and is therefore not accepted as reliable, while the earlier MEGA run passed
22 Hz. The conservative system recommendation is **20 Hz until 22 Hz is
repeated with additional trials**. The transport delivered approximately
**31–32 Hz** at requested settings from 30–40 Hz, but those frames were not
reliably valid full universes.

## Authoritative grounded Pico results

| requested Hz | delivered Hz | updates | inferred lost | loss % | pattern errors | max gap ms | verdict |
|---:|---:|---:|---:|---:|---:|---:|:---|
| 5 | 5.02 | 301 | 0 | 0.00 | 0 | 227 | RELIABLE |
| 10 | 9.88 | 593 | 4 | 0.70 | 0 | 205 | RELIABLE |
| 15 | 15.52 | 931 | 5 | 0.50 | 0 | 136 | RELIABLE |
| 20 | 19.67 | 1180 | 6 | 0.50 | 0 | 114 | **RELIABLE CEILING** |
| 22 | 23.12 | 1387 | 12 | 0.90 | 76 | 91 | NOT RELIABLE |
| 25 | 16.72 | 1003 | 40 | 3.80 | 40 | 681 | NOT RELIABLE |
| 27 | 23.28 | 1397 | 4 | 0.30 | 54 | 114 | NOT RELIABLE |
| 30 | 31.28 | 1877 | 2 | 0.10 | 676 | 137 | NOT RELIABLE |
| 32 | 31.60 | 1896 | 5 | 0.30 | 699 | 91 | NOT RELIABLE |
| 35 | 31.67 | 1900 | 6 | 0.30 | 714 | 91 | NOT RELIABLE |
| 37 | 31.83 | 1910 | 5 | 0.30 | 697 | 69 | NOT RELIABLE |
| 40 | 31.63 | 1898 | 8 | 0.40 | 722 | 91 | NOT RELIABLE |

The final 10 Hz grounded smoke run (`20260902_154700`) recorded 99 updates at
9.90 Hz, zero inferred loss, zero pattern errors, and a 136 ms maximum gap.

## MEGA comparison

The MEGA baseline passed 5–22 Hz with zero pattern errors and identified 22 Hz
as its reliable ceiling in that run. Both monitors agree on the important
system-level shape: rates track the request at low rates, corruption begins in
the low-to-mid-20 Hz transition region, and 30–40 Hz reaches a roughly 31–32 Hz
throughput plateau but fails full-universe validation.

The exact boundary differs between one-run monitor captures (Pico: 20 Hz
accepted; MEGA: 22 Hz accepted), so this is not evidence that the Pico or MEGA
changes the wireless system limit. Repeat 20/22/25 Hz trials before selecting a
production ceiling above 20 Hz.

## Acceptance rule

A point is reliable when inferred sequence loss is at most 5%, pattern errors are
zero, and there is no sustained multi-period outage. Pattern errors are a hard
failure because the monitor validates all 512 channels of each new payload; a
changed-sequence frame with a bad channel is not a valid complete universe.

## Monitor and grounding notes

The final Pico monitor uses the installed `Pico-DMX` library's PIO plus DMA
capture on GPIO 1. The DMA completion callback accounts for the completed
513-byte frame before the library re-arms the DMA buffer, avoiding foreground
read/write races. Telemetry uses native USB CDC. The runner supports
`--monitor-type pico` and tolerates Pico USB sessions that do not replay a boot
banner when the port opens.

The first Pico sweeps were invalidated because the Pico and DMX source did not
share ground. All Pico-tagged runs from those attempts were deleted before the
authoritative grounded run. The remaining Pico artifacts are only the valid
grounded smoke and full sweep listed above.

## TX/receiver scope

The TX-only safety fix clamps the effective pacing interval at zero when the
requested period is no greater than the estimated 27 ms transmission overhead,
preventing unsigned underflow. The receiver source, receiver libraries, and
receiver firmware were not modified.

## Reproduction

```bash
python3 Testing/feature7/tools/analyze.py Testing/feature7/runs/20260902_154822
python3 Testing/feature7/tools/analyze.py --json Testing/feature7/runs/20260902_154822
```
