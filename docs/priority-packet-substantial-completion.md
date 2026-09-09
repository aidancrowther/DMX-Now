# Targeted Priority Packet: Substantial Completion

**Status:** Substantially complete and ready for feature-branch merge review  
**Branch:** `channel_gating`
**Date:** 2026-09-09

## Scope completed

The targeted priority packet path is implemented across the host daemon,
transmitter, receiver, and shared protocol:

- Added distinct priority and priority-completion packet types.
- Added host-to-transmitter management commands for priority marking and ACK
  retrieval.
- Added complete-universe priority transmission with repeat count, TTL, and
  bounded queueing.
- Added receiver-targeted transaction sequencing and per-receiver state.
- Added receiver completion ACK handling, duplicate/invalid/unknown ACK
  accounting, and retry/recovery behavior.
- Added runtime receiver hard-gate enforcement using a 512-byte write-permission
  table and a no-gates fast path.
- Added staged priority gate metadata with atomic application after complete
  priority reconstruction.
- Added queue-aware transmitter metadata delivery and explicit gate-application
  completion status.
- Fixed the management-interface crash when editing a hard-locked channel.
- Added lead-in and lead-out timing so priority traffic is separated from the
  normal 20 Hz DMX stream.
- Preserved normal latest-state DMX pacing outside priority transactions.
- Added host tests for service behavior and priority transaction handling.
- Added a hardware transition acceptance runner at
  `wireless_dmx_daemon/tests/run_priority_transition.py`.

## Acceptance evidence

The following live hardware tests were completed with the normal firmware on
the transmitter and both receivers:

### Targeted priority test

- 10 priority events submitted.
- Both receivers acknowledged every event.
- 10/10 first-attempt successes.
- 0 retry-recovered events.
- 0 failed events.
- 0 invalid or unknown ACKs.

### Extended two-receiver soak

- 20 events with 15-second spacing.
- 20/20 first-attempt successes.
- Both receivers acknowledged every event.
- 0 retry-recovered events.
- 0 failed events.
- 0 invalid or unknown ACKs.
- Process exit status: `0`.

### Priority-to-normal transition

The transition runner uses three separate Mega measurement windows:

1. Normal DMX output before priority.
2. Priority DMX output while the transaction is active.
3. Normal DMX output after ACK completion and a three-second settling period.

The final run passed all phases:

```text
normal before: 222 checks, 222 pass, 0 fail
priority:      311 checks, 311 pass, 0 fail
normal after:  355 checks, 355 pass, 0 fail
receiver ACKs: both expected receivers acknowledged
exit code:     0
```

The post-priority settling period is intentional. An earlier version measured
immediately at the end of the transaction and captured six transient settling
frames. Extending the settle period makes the test distinguish a bounded
transition from a persistent failure to resume normal DMX.

### Receiver hard-gate transition

The Mega-connected receiver was tested independently with the second receiver
excluded from event construction to avoid stale telemetry ambiguity:

```text
normal baseline:        266 checks, 266 pass, 0 fail
priority gate establish: 310 checks, 310 pass, 0 fail
normal while locked:    267 checks, 267 pass, 0 fail
priority unlock:        311 checks, 311 pass, 0 fail
normal after unlock:    267 checks, 267 pass, 0 fail
```

The lock transaction and unlock transaction both completed with the expected
receiver ACK. During the locked phase, normal packets carrying a different
value were transmitted but the receiver continued outputting the priority
value. After the all-clear priority transaction, normal output resumed.

The current 20-event soak was also scoped to that receiver:

```text
events: 20
first-attempt successes: 20
failed events: 0
unknown ACKs: 0
invalid ACKs: 0
retry failures: 0
```

## Automated validation

The host test suite currently passes in full:

```text
63 passed
```

The transition runner passes Python compilation and repository whitespace
validation.

## Running the transition test

With the transmitter on `/dev/ttyUSB0`, the Mega monitor on `/dev/ttyUSB1`, and
both receivers online, run:

```bash
cd wireless_dmx_daemon
python tests/run_priority_transition.py \
  --tx-port /dev/ttyUSB0 \
  --mega-port /dev/ttyUSB1 \
  --expected-receiver 0x00DAFF38 \
  --expected-receiver 0x00DB07D7 \
  --output /tmp/priority-transition.json
```

The command returns zero only when normal output is valid before and after the
priority transaction, the priority output is observed, and both receivers
complete the transaction.

## Remaining qualification

This feature is substantially complete for merge into `master`. A formal
60-minute priority verification run remains recommended post-merge. A
two-receiver hard-gate run is also pending until both receiver units are
confirmed to be running the matching receiver firmware simultaneously.

Other existing project follow-up items remain unchanged, including native
Windows/macOS virtual serial support, broader fault-injection coverage, and a
future GUI.
