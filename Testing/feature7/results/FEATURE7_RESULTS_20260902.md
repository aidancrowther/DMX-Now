# Feature 7 Results — Automated Refresh-Rate Sweep

**Run:** `Testing/feature7/runs/20260902_132200/`  
**Date:** 2026-09-02  
**Hardware:** ESP-NOW TX `/dev/ttyUSB0`, MEGA monitor `/dev/ttyUSB1`, integrated receiver unchanged  
**Configuration:** `WIRELESS_TX_OVERHEAD_MS=27`, `WIRELESS_TX_DRAIN_TIMEOUT_MS=100`  
**Per point:** 10 s settling + 60 s silent measurement  

## Executive conclusion

The highest tested setting meeting the defined reliability criteria is **22 Hz
requested**, delivering **23.93 Hz** with **0.30% inferred sequence loss** and
**zero pattern errors**. This is the recommended reliable ceiling from this
sweep.

The transport reaches a practical delivered-rate plateau of approximately
**31–32 Hz** at requested settings from 30–40 Hz. However, pattern errors become
frequent at 27 Hz and above, so that plateau must not be described as reliable
full-universe delivery.

The 25 Hz point is the transition region: it delivered 24.73 Hz with only one
pattern error in 60 seconds. Under the strict zero-pattern-error criterion it
is not accepted; it is a candidate for repeat testing if a less conservative
operating point is desired.

## Results

| requested Hz | delivered Hz | updates | inferred lost | loss % | pattern errors | max gap ms | verdict |
|---:|---:|---:|---:|---:|---:|---:|:---|
| 5 | 5.02 | 301 | 1 | 0.30 | 0 | 383 | RELIABLE |
| 10 | 10.00 | 600 | 2 | 0.30 | 0 | 203 | RELIABLE |
| 15 | 15.25 | 915 | 8 | 0.90 | 0 | 158 | RELIABLE |
| 20 | 19.78 | 1187 | 11 | 0.90 | 0 | 114 | RELIABLE |
| 22 | 23.93 | 1436 | 5 | 0.30 | 0 | 90 | **RELIABLE CEILING** |
| 25 | 24.73 | 1484 | 6 | 0.40 | 1 | 91 | NOT RELIABLE |
| 27 | 24.50 | 1470 | 3 | 0.20 | 55 | NOT RELIABLE |
| 30 | 31.42 | 1885 | 8 | 0.40 | 662 | 90 | NOT RELIABLE |
| 32 | 32.05 | 1923 | 3 | 0.20 | 766 | 90 | NOT RELIABLE |
| 35 | 31.97 | 1918 | 16 | 0.80 | 698 | 90 | NOT RELIABLE |
| 37 | 31.60 | 1896 | 21 | 1.10 | 695 | 90 | NOT RELIABLE |
| 40 | 31.77 | 1906 | 17 | 0.90 | 711 | 69 | NOT RELIABLE |

## Acceptance rule

A point is reliable when inferred sequence loss is ≤5%, pattern errors are zero,
and there is no sustained multi-period outage. Pattern errors are treated as a
hard failure because the monitor validates all 512 channels of each new payload;
a frame with an error is not accepted as a valid complete universe.

## Analysis

* **5–22 Hz:** delivered rate follows the requested rate closely. Loss remains
  below 1% and all 512-channel pattern checks pass. The 20/22 Hz difference is
  consistent with pacing/measurement quantization, not a rate collapse.
* **25 Hz:** first observed pattern error. This is the boundary region and should
  be repeated if operating near the ceiling is important.
* **27 Hz:** only 24.50 Hz delivered despite the higher request, indicating the
  beginning of contention/throughput limitation; 55 pattern errors confirm that
  complete universes are no longer consistently reconstructed.
* **30–40 Hz:** delivered rate is approximately 31–32 Hz rather than tracking the
  request. Pattern errors rise to 662–766 per 60-second run while sequence-loss
  percentages remain comparatively small. This distinction matters: the receiver
  is often producing a changed sequence, but the full payload is not always
  valid.
* `max_gap` is generally around one or two physical DMX periods at high rates,
  not evidence of a sustained link outage.

## Monitor validation and interference investigation

The MEGA was changed to a command-driven silent recorder. It receives DMX through
the DMXSerial UART ISR, accepts `START <settle> <measure>`, emits no USB output
during the measurement, and reports one result afterward. The final monitor uses
`packetReady()` for complete physical-frame detection, immediately copies the
513-byte DMXSerial buffer, then performs validation on the copy. This avoids
reading the mutable library buffer while the next physical frame is arriving.

A two-part full-frame hash was tested as an alternative to channel-1 duplicate
filtering. It caused 48–52 pattern errors in short 10 Hz smoke tests, compared
with zero errors after the snapshot change. It was rejected as too expensive for
the single-buffer ATmega2560 monitor. The `DmxSniff` example was also rejected
for this measurement because it uses `dataUpdated()`, which can fire for each
changed channel byte rather than once per complete frame.

The final 10 Hz smoke run recorded 101 updates in 9 measured seconds, 0 loss, and
0 pattern errors. The full 60-second sweep likewise had zero pattern errors
through 22 Hz, supporting that the final monitor path is not introducing the
observed high-rate errors.

## TX/receiver decision

The TX-only safety fix retained for this run clamps the budget interval at zero
when `1000 / WIRELESS_REFRESH_HZ <= WIRELESS_TX_OVERHEAD_MS`, preventing unsigned
underflow at high requested rates. The 27 ms overhead and 100 ms drain timeout
were unchanged for the comparison sweep.

No receiver source or firmware was modified. The high-rate signature is
consistent with the existing receiver/reconstruction path becoming unable to
produce valid full universes under the burst load, but this report does not
claim a receiver fix is required without a controlled repeat. Any receiver-side
queue/buffering or promotion change requires explicit approval before work begins.

## Reproduction

```bash
python3 Testing/feature7/tools/analyze.py Testing/feature7/runs/20260902_132200
python3 Testing/feature7/tools/analyze.py --json Testing/feature7/runs/20260902_132200
```
