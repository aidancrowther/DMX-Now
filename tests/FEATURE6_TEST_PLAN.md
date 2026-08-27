Feature 6 Test Plan — Receiver Reconstruction + Double Buffering
================================================================
Both test programs compile successfully via the existing scripts:
  ./flash_espnow_tx.sh   # compile-only, no -f (default OFF fault hooks)
  ./flash_espnow_rx.sh   # compile-only, no -f

No FreeRTOS or any RTOS code was introduced. All state is managed with
plain Arduino setup()/loop() and a small, deterministic state machine.

Files modified in place (no duplicates created):
  tests/espnow_universe_rx/espnow_universe_rx.ino
  tests/espnow_universe_tx/espnow_universe_tx.ino
  tests/FEATURE6_TEST_PLAN.md (this file)

## Test 1: normal complete frame
TX compile settings: none (default). Expected TX output: "TX FRAME seq=0 fragments=3". RX output: one line per fragment ending with "RX COMPLETE seq=0 ...". Active sequence becomes 0, hasActiveWirelessFrame=true.

## Test 2: dropped middle fragment
TX compile settings: #define TEST_DROP_FRAGMENT_INDEX 1. TX output: omits the middle fragment (no "TX FRAG seq=X frag=2/3"). RX output: two fragments received then abandoned when next frame arrives, activeUniverse unchanged.

## Test 3: dropped final fragment  
TX compile settings: none (default). Expected TX output: only two fragments per frame (final missing from radio or not counted). RX output: staging never reaches coverageFull; remains incomplete forever until next valid frame arrives.

## Test 4: duplicate fragment
TX compile settings: #define TEST_DUPLICATE_FRAGMENT_INDEX 1. TX output: "TX FRAG" printed twice for one fragment index. RX output: duplicate counter increments, frame still completes normally.

## Test 5: reordered fragments
TX compile settings: #define TEST_REORDER_FRAGMENTS. TX output: fragments arrive in order 2,0,1 (note the unusual sequence). RX output: reconstruction succeeds regardless of arrival order; integrity passes.

## Test 6: late stale fragment
TX compile settings: none (default), then delay > STAGING_TIMEOUT_MS before sending a delayed fragment from an earlier frame. RX output: "RX STALE" message, staging state remains on newer sequence.

## Test 7: corrupted payload
TX compile settings: #define TEST_CORRUPT_FRAGMENT_INDEX 1; #define TEST_CORRUPT_BYTE 0. TX output: one line shows the corruption. RX output: fragment count reaches 3 but fullIntegrityCheck fails, so promotion does not occur and activeUniverse remains previous good frame.

## Test 8: malformed metadata/bounds
TX compile settings: none (default). Use TEST_INJECT_MALFORMED in the receiver to feed an invalid packet. RX output: malformed counter increments, no staging change.

## Test 9: receiver starts mid-stream
TX compile settings: none. TX already at seq=100 when RX boots. RX output: first complete valid frame accepted regardless of sequence number; hasActiveWirelessFrame=true after promotion.

## Test 10: transmitter reset
TX compile settings: none. After RX accepts several frames, reset TX so sequence restarts at 0. RX behavior: the new frames with lower sequence values are either stale (if link live) or accepted as a re-baseline after TRANSMITTER_RESET_RECOVERY_MS of silence.

## Test 11: uint32 sequence rollover
TX compile settings: #define TEST_SEQUENCE_WRAP. TX output: starts at 0xFFFFFFFE, then wraps to 0. RX output: accepts the wrap as forward progression; older pre-wrap fragments marked stale.

## Test 12: multiple receivers
TX compile settings: none (default). Use two RX sketches running simultaneously on separate ESPs. Both receive and reconstruct independently without acknowledgements.

RAM usage (Feature 6 receiver): 32,224 / 80,192 bytes RAM (40%), 245,008 / 1,048,576 bytes Flash (23%).
