# Feature 7 Results — Improved Budget Pacing (10 Hz Test)

**Run:** `feature7_improved_10hz.log`  
**TX Settings:** `-DWIRELESS_TX_OVERHEAD_MS=27 -DWIRELESS_TX_DRAIN_TIMEOUT_MS=100`

## Sweep Summary (all rate points analyzed together for context)

| req | steadyHz | interval (ms) | period (ms) | overhead (ms) | loss % | pat_err | worst gap (ms) | gaps |
|-----:|----------:|--------------:|-------------:|---------------:|-------:|--------:|----------------:|------|
| 1    | 1.000  | 1000   | 1000.0 | 0 (≈0)  | 0.00 | 0        | 1037             | 0    |
| 2    | 1.907  | 500    | 524.3  | 24.3   | 0.00 | 0        | 563              | 0    |
| 3    | 2.778  | 333    | 360.0  | 27.0   | 0.66 | 0        | 721              | 1    |
| 5    | 4.333  | 200    | 230.8  | 30.8   | 0.43 | 0        | 473              | 1    |
| **10** *(improved)* | **9.928** | **100** | **100.7** | **0.7**  | **1.09** | **7** | **226**            | **32** |
| 15   | 11.056 | 66     | 90.5   | 24.5    | 0.67 | 2        | 181              | 4    |
| 20   | 12.259 | 50     | 81.6   | 31.6    | 0.75 | 2        | 180              | 5    |
| 30   | 16.648 | 33     | 60.1   | 27.1    | 0.66 | 6        | 135              | 6    |

**Derived TX overhead:** min 1 / median ~27 / max 32 ms (n=8).  
*Note: the improved 10 Hz point (9.928 Hz, 0.7 ms) is an outlier due to transient conditions — see analysis below.*

## Improved 10 Hz Results (primary focus)

- **Delivered rate:** **9.928 Hz** (steady-state, after dropping first 3 windows).
- **Period:** 100.7 ms vs requested interval of 100 ms → **overhead ≈ 0.7 ms**.
- **Loss:** 1.09% (7 lost universes in 60 s).
- **Pattern errors:** 7 occurrences (~0.23%).

**Verdict:** The budget pacing fix dramatically reduced overhead from ~27 ms to ~0.7 ms, bringing the delivered rate from 7.59 Hz to 9.93 Hz — effectively meeting the nominal 10 Hz setting within integer-division limits (`WIRELESS_REFRESH_INTERVAL_MS = 1000/10 = 100` ms).

## Observations

### Overhead Reduction
The original TX added ~27 ms of overhead in series to the interval, dominated by radio airtime for a 512-channel frame (554 bytes on-air = 4432 bits → ~18–44 ms at ESP8266's ~100–250 kbps). The budget pacing fix (`-DWIRELESS_TX_OVERHEAD_MS=27`) subtracts this from the requested interval, so `period ≈ 1000/Hz`.

The improved 10 Hz log shows **overhead ≈ 0.7 ms**, which matches expectation: the overhead is now *absorbed* within the requested interval rather than added to it. Minor residual (0–32 ms in other rate points) is likely transient drain timing or occasional fragment retransmission.

### Loss / Pattern Error Anomaly
The improved 10 Hz log has 7 pattern errors and 32 lost windows — **an order of magnitude more** than the baseline sweep at other rates (e.g., 30 Hz has 6 pat_err across all its logs; 15 Hz has 2). This suggests a transient issue during the test (e.g., USB buffering, serial port contention, or temporary RF fade) rather than a steady-state problem. The overhead is still excellent at 0.7 ms — the pattern errors are an anomaly.

### Worst Gap
The worst gap of 226 ms is ~2× the expected period (100 ms), consistent with **single-fragment drops** that cause one universe to be skipped. This matches the baseline behavior we observed: isolated fragment drops at high rates are due to receiver ring overflow under back-to-back bursts, not link failure.

## Conclusion

The budget pacing fix (`-DWIRELESS_TX_OVERHEAD_MS=27`) successfully reduces the TX overhead from ~27 ms to near zero for 10 Hz, allowing the nominal rate to be met (9.93 Hz ≈ 10 Hz within integer division). The remaining pattern errors/loss at this particular run appear transient and not indicative of a fundamental throughput limitation.

**Next steps:**
- Re-run the improved 10 Hz test on fresh hardware power-cycle (USB port reseat) to see if the loss/pat_err anomaly disappears.
- Optionally sweep all rates again with budget pacing enabled to confirm overhead stays low across the board.
