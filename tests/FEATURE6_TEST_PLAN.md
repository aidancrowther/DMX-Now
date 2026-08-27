Feature 6 Test Plan — Receiver Reconstruction + Double Buffering
================================================================
Both test programs compile successfully via the existing scripts:
  ./flash_espnow_tx.sh   # compile-only, no -f (fault hooks DEFAULT OFF)
  ./flash_espnow_rx.sh   # compile-only, no -f

To enable a test hook, pass it with --define (the scripts add it to
build.extra_flags). Multiple hooks can be passed in one invocation:
  ./flash_espnow_tx.sh --define -DTEST_DROP_FRAGMENT_INDEX=2
  ./flash_espnow_rx.sh --define -DTEST_INJECT_MALFORMED
  ./flash_espnow_tx.sh -f --define -DTEST_DELAYED_FRAGMENT   # compile + flash

No FreeRTOS or any RTOS code was introduced. All state is managed with
plain Arduino setup()/loop() and a small, deterministic state machine.

Files involved:
  tests/espnow_universe_rx/espnow_universe_rx.ino   (receiver under test)
  tests/espnow_universe_tx/espnow_universe_tx.ino   (transmitter / fault injector)
  tests/FEATURE6_TEST_PLAN.md (this file)

Conventions used below:
  - "TX setting" is the --define value to add to the TX build (or "none").
  - RX serial output is the source of truth for pass/fail; the 5 s "RX STATS"
    line aggregates the counters.
  - All tests are deterministic unless otherwise noted; re-run if RF is noisy.

## Test 1: normal complete frame
TX setting: none (default).
Expected TX: "TX FRAME seq=N fragments=3", three "TX FRAG" lines, "TX FRAME complete".
Expected RX: three fragments accepted, then "RX COMPLETE seq=N ..." with the
six sample bytes printed. Stats: complete=1, integrityFail=0, hasActiveWirelessFrame=true.
PASS: active sequence advances and stays correct across multiple frames.

## Test 2: dropped middle fragment
TX setting: --define -DTEST_DROP_FRAGMENT_INDEX=1
Expected TX: only fragments 1/3 and 3/3 transmitted (no "TX FRAG ... frag=2/3").
Expected RX: two fragments received for each frame; the incomplete frame is
abandoned by EITHER the 2 s staging timeout OR superseded when the next frame's
fragments arrive — whichever hits first. activeUniverse is NOT changed (the
previous complete frame remains). Stats: abandon (abandonedIncomplete and/or
abandonedTimeout) increments, complete stays 0 (or unchanged if a prior frame
had completed).
PASS: no promotion occurs while a fragment is missing; active universe is stable.

## Test 3: dropped final fragment
TX setting: --define -DTEST_DROP_FRAGMENT_INDEX=2
Expected TX: only fragments 1/3 and 2/3 transmitted (no "TX FRAG ... frag=3/3").
Expected RX: coverage never reaches full (only 472 of 512 bytes covered); the
frame is abandoned (timeout or supersede) each cycle. activeUniverse unchanged.
PASS: a missing final fragment can never produce a false "complete" frame.

## Test 4: duplicate fragment
TX setting: --define -DTEST_DUPLICATE_FRAGMENT_INDEX=1
Expected TX: fragment 2/3 transmitted twice per frame (4 slots, count stays 3).
Expected RX: duplicate counter increments for the repeated fragment; the frame
still completes and promotes exactly once. Stats: dup>=1, complete=1, integrityFail=0.
PASS: duplicates are not double-counted and do not block or corrupt promotion.

## Test 5: reordered fragments
TX setting: --define -DTEST_REORDER_FRAGMENTS
Expected TX: fragments transmitted in order 3/3, 1/3, 2/3.
Expected RX: reconstruction succeeds regardless of arrival order (coverage
bitmap + unique-count are order-independent); "RX COMPLETE" with integrity PASS.
PASS: arrival order does not affect the reconstructed universe.

## Test 6: late stale fragment
TX setting: --define -DTEST_DELAYED_FRAGMENT
Behavior: after each normal frame completes, the TX holds ~2.5 s, then re-sends
one fragment of that (already-active) frame. The 2.5 s hold is deliberately
between the RX STAGING_TIMEOUT_MS (2000) and TRANSMITTER_RESET_RECOVERY_MS (3000)
so the link is still "live" and the late fragment must be classified STALE.
Expected RX: the late fragment is NOT promoted and NOT re-baselined; the
"RX STALE seq=..." line appears (or the fragment is dropped as stale) and
activeUniverse is unchanged. Stats: stale increments.
PASS: a late duplicate of an active frame never regresses the active universe.
NOTE: this exercises the stale branch deterministically; the same branch is also
reached by Test 10 (fast transmitter reset).

## Test 7: corrupted payload
TX setting: --define -DTEST_CORRUPT_FRAGMENT_INDEX=1 --define -DTEST_CORRUPT_BYTE=0
Expected TX: one "TX CORRUPT seq=... frag=2 byte=0 -> 0x.." line per frame.
Expected RX: all 3 fragments arrive and coverage completes, but the full 512-byte
integrity check fails at the corrupted byte; the frame is NOT promoted.
Stats: integrityFail increments, complete does not. activeUniverse remains the
last good frame.
PASS: a corrupt-but-complete frame is detected and rejected (no false promote).

## Test 8: malformed metadata / bounds
TX setting: none.
RX setting: --define -DTEST_INJECT_MALFORMED
Behavior: at startup the receiver builds a structurally-malformed packet
(offset+payload > 512) and feeds it through processPacket() directly.
Expected RX: "RX INJECT: feeding a malformed (overflow) packet to processPacket()",
then the malformed counter increments and staging/active state is unchanged.
PASS: malformed metadata is rejected without touching the buffers.
NOTE: build the RX with the hook (see command above), then run normally.

## Test 9: receiver starts mid-stream
TX setting: none. Start the TX and let it run to a high sequence, THEN power/boot
the RX (or use --define -DTEST_FORCE_SEQUENCE_START=100 on the TX and boot both).
Expected RX: the first complete, integrity-passing frame is accepted regardless
of the (non-zero) sequence; hasActiveWirelessFrame becomes true after promotion.
PASS: no sequence-0 assumption; the receiver locks onto the live stream.

## Test 10: transmitter reset (re-baseline)
TX setting: none. Let the RX accept several frames, then power-cycle the TX so
its sequence restarts at 0.
Expected RX: the new lower-sequence frames are treated as STALE while the link is
still live (silence < 3000 ms). Once the link has been quiet for >= 3000 ms, the
RX logs "RX REBASELINE permit seq=..." and re-baselines — but only commits when a
COMPLETE, integrity-passing frame arrives. activeUniverse never regresses.
Stats: stale may increment first, then rebase increments; complete resumes.
PASS: a restarted transmitter is re-acquired safely without a stale regression.

## Test 11: uint32 sequence rollover
TX setting: --define -DTEST_SEQUENCE_WRAP
Expected TX: sequence starts at 0xFFFFFFFE, then wraps 0xFFFFFFFE -> 0xFFFFFFFF -> 0.
Expected RX: the wrap is treated as forward progression (seqIsNewer uses signed
comparison); frames across the wrap are accepted; older pre-wrap fragments are
stale. No "re-baseline" is triggered by the wrap.
PASS: 0xFFFFFFFF -> 0 does not look like a reset/stale event.

## Test 12: multiple receivers
TX setting: none. Run two RX units (separate ESPs, same channel) simultaneously.
Expected: both independently receive, reconstruct, and promote the same complete
frames without any acknowledgement or per-receiver traffic.
PASS: broadcast scales to multiple receivers; both stay in lockstep with TX.

---
RAM/Flash (receiver, default build): 32,224 / 80,192 bytes RAM (40%),
245,008 / 1,048,576 bytes Flash (23%).
With TEST_INJECT_MALFORMED: 32,400 RAM, 245,200 Flash.
TX default: 29,332 RAM, 243,568 Flash.
TX with TEST_DELAYED_FRAGMENT: 29,436 RAM, 243,696 Flash.
(All compile-verified; hook code is compiled out when the define is absent.)
