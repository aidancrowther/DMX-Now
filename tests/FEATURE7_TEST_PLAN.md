# Feature 7 Test Plan — Reliable Wireless Refresh Rate

Goal: find **roughly what wireless refresh rate (Hz) the system can sustain
reliably**, using the real production receiver path and a host-logged metric
stream. "Reliable" = high delivered frame rate with low loss and no pattern
errors.

## What is measured

The **integrated** receiver (`receiver/receiver.ino`, ESP-01) is the unit under
test. It receives the QuickESPNow broadcast, reconstructs + double-buffers the
universe (Feature 6), and drives espDMX physical output. An **Arduino MEGA 2560**
sits on that DMX output as a monitor:

```
tests/espnow_universe_tx  --(ESP-NOW bcast, paces off WIRELESS_REFRESH_HZ)-->
receiver.ino (ESP-01)  --(MAX3485 DMX, 250k 8N2)-->  MEGA 2560 (DMXSerial RX)
   (pattern: universe[i]=(i+seq)&0xFF)                                        |
                                                                              USB Serial (115200) --> host PC
```

The MEGA counts genuinely-new universes, infers loss from frame-sequence gaps,
and reports a metric line to the host every second. This is the "program" the
user requested.

## Files

* `tests/dmx_refresh_monitor/dmx_refresh_monitor.ino` — the MEGA monitor (DMXSerial RX).
* `./flash_dmx_monitor.sh` — build/flash for the MEGA (passes `-DDMX_USE_PORT1`).
* `./flash_espnow_tx.sh` — build/flash for the Feature 5/6 TX (set rate via `--define`).
* `Testing/feature7_capture.py` — optional host helper: logs the MEGA stream and summarizes.
* `Testing/FEATURE7_RESULTS.md` — results table to fill in after runs.

## Hardware / wiring

* TX: an ESP8266 running `tests/espnow_universe_tx`, on channel 1.
* RX: the ESP-01 running `receiver.ino`, on channel 1, with a MAX3485 driving DMX.
* MEGA 2560:
  * DMX data (MAX3485 RO) -> **pin 19 (RX1 / USART1)**.
  * MEGA USB (pins 0/1) -> host PC (telemetry, 115200 8N1).
  * DMXSerial drives its default mode pin 2 to LOW in receiver mode (harmless here).
* Keep TX, RX, and MEGA power stable; note TX<->RX distance/obstacles (RF-dependent).

## Making the rate configurable (the Feature 7 change)

`WIRELESS_REFRESH_HZ` in `libraries/WirelessDMX/src/wireless_protocol.h` is now
`#ifndef`-guarded (default 1). Only the **TX** paces off it; the RX and MEGA are
rate-independent. Set the rate per run with a build define:

```bash
./flash_espnow_tx.sh --define -DWIRELESS_REFRESH_HZ=N      # compile-only
./flash_espnow_tx.sh -f --define -DWIRELESS_REFRESH_HZ=N    # compile + flash
```

The production default is now 20 Hz, based on the measured reliable RF ceiling.
The setting remains configurable, including experimental builds up to 40 Hz.

The integrated transmitter UART is `115200 8N2`; update host test tools and
lighting software accordingly.

## Building / flashing the monitor

```bash
./flash_dmx_monitor.sh                  # compile-only (MEGA, arduino:avr:mega)
./flash_dmx_monitor.sh -f --port /dev/ttyUSB1   # compile + flash
```

`DMX_USE_PORT1` is passed as a **global** build flag (`build.extra_flags`), not a
sketch `#define`, because the DMXSerial port is chosen inside the library's own
`DMXSerial.cpp` translation unit (verified via verbose build: the flag is on the
`DMXSerial.cpp` compile line). Result: DMX on USART1/pin 19; USB Serial free.

## How the MEGA measures (important details)

* **New-universe count:** on `DMXSerial.packetReady()` — a one-shot latch the library
  sets once per **complete** frame and clears when we read it, so the 512-channel
  buffer is fully settled before we read/validate it. espDMX retransmits the *same*
  active universe at ~44 Hz, so most of those complete frames are identical re-sends;
  we count a frame as NEW only when its sequence (channel 1 = `seq & 0xFF`) differs
  from the previous one, skipping identical retransmits. This isolates the delivered
  *wireless* refresh rate from the physical DMX rate.
  (We do NOT use `dataUpdated()`: the receive ISR re-sets it for *every* changed
  channel byte — up to 512×/frame — which counted one physical frame as many
  "updates" and let us read the buffer half-filled.)
* **Loss:** from frame-sequence gaps. DMX channel 1 = `universe[0]` = `seq & 0xFF`
  (= `seq8`). Between two consecutive new universes, `delta = (seq8 - prev) mod 256`;
  if `delta > 1` then `delta-1` universes were skipped. Summed across the window.
* **Pattern check:** every channel `c` (1..512) must equal `(seq8 + c - 1) & 0xFF`.
  (espDMX sends all 512 channels for this pattern — every channel changes each
  frame, so no trailing-zero trim — hence all 512 are checkable.) `pat_err` should
  be ~0 because the receiver gates promotion on a full 512-byte integrity check.
* **Liveness:** `no_data` (ms since any DMX data) and `max_gap` (longest inter-
  universe gap) expose stalls and jitter.

### Metric line (one per second)
`t=<s> updates=<n> rate=<f>Hz lost=<n> gaps=<n> loss=<f>% pat_err=<n> max_gap=<ms>ms last_seq8=<n> no_data=<ms>ms`

* `rate` = `updates / window` = **measured delivered refresh rate**.
* `loss` = `lost / (updates + lost)`.
* A rate is **reliable** if `loss` is low (target ≤ ~5%), `pat_err` ≈ 0, and
  `max_gap` stays well under a few frame intervals.

## Procedure (sweep)

Suggested sweep: **1, 2, 3, 5, 10, 15, 20, 30 Hz.**

For each rate:
1. Flash the TX at that rate (command above). Power-cycle the TX.
2. Confirm the RX (ESP-01) is up; the MEGA monitor is already flashed and running.
3. Let the stream settle (~10 s), then capture for a fixed window (e.g. 60 s).
4. Record the per-second lines (use `Testing/feature7_capture.py` or a serial
   monitor) and note the steady `rate`, `loss`, `pat_err`, `max_gap`.

Use `Testing/feature7_capture.py` to log + summarize, or any 115200-baud serial
terminal to capture the lines.

## Reading the results

* **Reliable ceiling** = the highest Hz where `loss` is low, `pat_err` ≈ 0, and
  `max_gap` is stable.
* **Achievable ceiling** = the highest steady `rate` (Hz) observed as the sweep
  rises (the plateau). This is "roughly what we can handle."
* If `rate` plateaus below the requested rate and `loss`/`gaps` climb, the
  wireless link (or the QuickESPNow RX queue) is the limiting factor. If `rate`
  tracks the requested value but `loss` grows, frames are being dropped/interleaved
  faster than they are assembled (latest-state supersede — expected at the edge).

## Caveats

* Results are RF/environment-dependent (2.4 GHz, channel 1, distance, obstacles,
  nearby traffic). Re-run if noisy; log TX<->RX distance.
* The MEGA's `seq8`-based loss uses the low byte of the sequence; it is exact
  unless ≥256 frames are skipped between two observed universes (unlikely).
* The integrated receiver's integrity check is locked to this deterministic
  pattern (see project memory) — fine here, since we test the test TX path.
