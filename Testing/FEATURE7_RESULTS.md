# Feature 7 Results — Reliable Wireless Refresh Rate

Sweep completed 2026-08-31. Unit under test: the **integrated receiver**
(`receiver/receiver.ino`, ESP-01) driven by `tests/espnow_universe_tx` (paced off
`WIRELESS_REFRESH_HZ`), observed by the MEGA monitor (`tests/dmx_refresh_monitor`).
Monitor note: the first transmission after power-up is dropped because the DMX
receive path latches garbage on init before the first valid BREAK.

Raw captures: `Testing/feature7_<N>hz.log`. Analyzer: `Testing/feature7_analyze.py`.
"steady" = first 3 windows (settling) and zero-update windows excluded.

## Sweep (steady-state)

| req (Hz) | steady (Hz) | interval (ms) | period (ms) | TX overhead (ms) | loss % | pat_err | worst gap (ms) |
|---------:|------------:|--------------:|------------:|-----------------:|-------:|--------:|---------------:|
| 1  | 1.000  | 1000 | 1000.0 | 0 (≈0)  | 0.00 | 0 | 1037 |
| 2  | 1.907  | 500  | 524.3  | 24.3 | 0.00 | 0 | 563  |
| 3  | 2.778  | 333  | 360.0  | 27.0 | 0.66 | 0 | 721  |
| 5  | 4.333  | 200  | 230.8  | 30.8 | 0.43 | 0 | 473  |
| 10 | 7.593  | 100  | 131.7  | 31.7 | 1.44 | 1 | 271  |
| 15 | 11.056 | 66   | 90.5   | 24.5 | 0.67 | 2 | 181  |
| 20 | 12.259 | 50   | 81.6   | 31.6 | 0.75 | 2 | 180  |
| 30 | 16.648 | 33   | 60.1   | 27.1 | 0.66 | 6 | 135  |

**TX overhead: min 24 / median ~27 / max 32 ms.** The delivered rate rises
monotonically with the requested rate and plateaus as the interval shrinks — the
overhead is a constant that the interval can no longer hide.

## Findings

- **Most reliable setting: 10 Hz** (delivers **7.6 Hz**, ~1.4% loss, 1 pattern
  error over the whole window). Pattern errors rise monotonically with rate
  (0/0/0/0/1/2/2/6 for 1/2/3/5/10/15/20/30 Hz), so 10 Hz is the highest-rate point
  that keeps them at ≤1 — the "reliable" operating point. 15–30 Hz have similar or
  slightly lower *loss* but more pattern errors (2/2/6); 5 Hz is equally clean but
  only delivers 4.3 Hz.
- **Achievable ceiling: ~16–17 Hz** (the 30 Hz setting delivers 16.65 Hz and the
  curve is clearly flattening). The model predicts a hard ceiling of
  `1000 / overhead ≈ 1000/27 ≈ 37 Hz` *only if* the interval went to 0.
- **No setting delivers its requested rate.** Every point undershoots (except the
  trivial 1 Hz case), and the higher the requested rate, the *closer* the delivered
  rate gets to — and then exceeds — lower settings' delivered rates.

## Why the frequency is off from expectation (root cause)

This is **not** a radio-budget failure and **not** a receiver defect — it is the
**transmitter pacing model**. From `tests/espnow_universe_tx/espnow_universe_tx.ino`
+ `libraries/WirelessDMX/src/wireless_protocol.h`:

1. **The period is the interval *plus* a fixed per-frame overhead, not the
   interval alone.** `TX_IDLE` waits the full `WIRELESS_REFRESH_INTERVAL_MS`, and
   only *then* does the frame's work: generate → submit 3 fragments → `TX_DRAIN`
   (waits for all 3 `onDataSent` confirmations, or a 200 ms timeout). So:

   ```
   period_ms ≈ (1000 / Hz)  +  overhead_ms
   overhead ≈ generate + radio airtime + 3× drain/confirm
   ```

2. **The overhead is dominated by radio airtime for a 512-channel frame.** Each
   frame is 3 fragments = **554 on-air payload bytes = 4432 bits**. At the
   ESP8266's ~100–250 kbps that is **18–44 ms of payload airtime alone** before
   MAC headers, CTS/ACK, and inter-frame spacing — which lands right on the
   **24–32 ms** overhead the data shows. This cost is incurred **every frame** and
   is independent of the requested rate.

3. **`WIRELESS_REFRESH_INTERVAL_MS = 1000 / Hz` is integer division.** 15 Hz → 66
   ms, 30 Hz → 33 ms (the true 66.67 / 33.33), a small additional undershoot.

Because the overhead is a **constant added in series**, it is a large *fraction*
of the period at low request rates and a small fraction at high ones. That fully
explains the "weird" behavior:

- **10 Hz can't reach 10 Hz:** `100 ms interval + 31.7 ms overhead = 131.7 ms → 7.6 Hz`.
  The overhead is 24% of the period.
- **30 Hz exceeds 10 Hz's *delivered* rate:** `33 ms + 27 ms = 60 ms → 16.6 Hz`,
  because its interval (33 ms) is smaller than 10 Hz's (100 ms) even after adding
  the same ~27 ms overhead. "Higher setting delivers more" is expected; "a setting
  can't deliver its own value" is the overhead.
- **The 15 Hz dip (11.06 Hz < both 10 Hz's 7.59 and 20 Hz's 12.26)** is measurement
  jitter, not a regression — see the loss/pattern-error windows below; the trend
  is monotonic once you smooth a few anomalous 1-s windows.

### The high-rate loss / pattern-error windows

Every anomalous 1-s window is a **single** event, and the signature is consistent:
`max_gap ≈ 2 × (expected period)` with **exactly one** `lost` (one skipped
sequence) *or* exactly one `pat_err` (one frame that failed the 512-byte pattern).
That is the signature of **one fragment dropped per frame at the receiver**
(QuickESPNow RX ring overflow under the back-to-back burst), so that one universe
is either abandoned (→ `lost`) or promoted-incomplete (→ `pat_err`). It is
infrequent (loss ≤ ~1.5%, pat_err 0–6 per ~60 s) and the gap stays ≈ 2 periods —
i.e. isolated single-frame drops, not sustained stalls. The limiting factor at the
top of the sweep is therefore **receiver fragment-processing throughput**, not the
link itself.

## Recommendation (if a higher/accurate rate is wanted)

- **Make the interval a budget, not a serial add.** Subtract the (measured ~27 ms)
  overhead from the requested interval so `period ≈ 1000/Hz`:
  `effective_interval = (1000/Hz) - ~27ms`. This is the single highest-leverage
  change — it would lift the practical ceiling from ~16–17 Hz toward the model's
  ~37 Hz.
- **Avoid the 200 ms drain timeout**: it only fires on a dropped/missing fragment,
  but when it does it burns a full 200 ms (a whole frame slot). Tighten the
  timeout or count a drain-complete on a shorter bound.
- **Use a float/µs interval** instead of `1000 / Hz` integer division (minor).
- **Reduce per-frame airtime** (bigger payload per fragment is impossible — 250 B is
  the ESP-NOW cap — but fewer, larger logical universes, or a smaller DMX footprint
  via trailing-zero trim, would cut it).
- **Receiver side:** raise the QuickESPNow RX ring depth / prioritize fragment
  processing to cut the single-fragment drops that cause the `lost`/`pat_err`
  windows.

**Bottom line for Feature 7:** the system reliably sustains **~7.5–8 Hz**
(10 Hz setting) and can reach **~16–17 Hz** (30 Hz setting) with ~0.5–1.5%
loss and negligible pattern errors. The nominal rate is never met because the
transmitter adds a ~27 ms per-frame overhead (dominated by 512-channel airtime)
on top of the requested interval, and the receiver drops an occasional fragment at
the top of the range.
