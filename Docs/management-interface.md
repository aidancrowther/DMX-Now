# Management interface

The DMX Now management interface is a binary, CRC-protected control plane that
shares the transmitter UART with the ENTTEC DMX stream. It is intentionally
separate from normal DMX payloads and never emits diagnostic text during normal
operation.

![Management interface flow](images/management-interface.svg)

## Frame format

Every host-to-transmitter management frame is:

```text
A5 5A | version | opcode | length low | length high | payload | CRC low | CRC high
```

The CRC is CRC-16/CCITT over `version`, `opcode`, `length`, and `payload`; the
two sync bytes are excluded. The transmitter parser is byte-wise, bounded, and
recovers by searching for the next sync sequence after malformed input.

## Host request opcodes

| Opcode | Name | Payload | Response/behavior |
|---:|---|---|---|
| `0x01` | Get receiver telemetry | empty | Multipart telemetry response. |
| `0x02` | Mark next priority | priority ID, target, repeats, attempt, optional gate mask | Transmitter classifies the next complete ENTTEC universe as priority. |
| `0x03` | Get priority ACKs | empty | Bounded priority ACK report. |
| `0x04` | Clear receiver cache | empty | Clears transmitter telemetry/ACK cache and returns cache-cleared response. |
| `0x05` | Set receiver fail-safe | mode, timeout, generation | Transmitter broadcasts the receiver configuration three times. |
| `0x06` | Set receiver output | enabled, target ID, generation | Transmitter broadcasts a targeted or all-online MAX3485 output change. |
| `0x07` | Locate receiver | target ID, duration, generation | Receiver disables DMX and pulses GPIO1/GPIO2 for the requested interval; the default is 15 seconds and the valid range is 1–15 seconds. |
| `0x08` | Set transmitter mode | one byte: `0` bridge or `1` management-only | Changes the runtime transmitter role unless the firmware was statically locked. Response `0x88` reports accepted/rejected status and active mode. |
| `0x09` | Get transmitter mode | empty | Queries the current runtime role without changing it. Response `0x88` reports the active mode. |
| `0x0A` | Get observed universe | empty | Returns three CRC-protected `0x8A` parts containing the latest complete normal-DMX observation or the transmitter's local fallback. |
| `0x0B` | Retransmitter locate | target ID, duration, generation | Priority-queued locate packet; locate state is confirmed by retransmitter telemetry. Production retransmitters keep DMX input enabled and use GPIO2 for the locate indicator. |

The Python codec is in:

```text
Host Software/wireless_dmx_daemon/wireless_dmx/transmitter/management.py
```

The shared embedded declarations are in:

```text
Libraries/WirelessDMX/src/wireless_protocol.h
```

## Queueing and ordering

The transmitter has separate bounded queues for:

- latest-state normal DMX;
- ordinary management requests;
- priority management markers.

The daemon queries the current mode after connection and reconnect. If it does
not match the configured role, it sends a mode-set request and waits for the
accepted response before clearing the receiver cache. Firmware may be statically locked with
`TRANSMITTER_LOCK_BRIDGE` or `TRANSMITTER_LOCK_MANAGEMENT_ONLY`; a rejected
request leaves the current firmware role unchanged. The legacy
`TRANSMITTER_MANAGEMENT_ONLY` define remains an alias for a locked
management-only image.

Priority markers are serviced ahead of ordinary management traffic so telemetry
polling cannot silently turn a priority universe into a normal universe. Normal
DMX remains latest-state: a newer unsent universe replaces an obsolete one.

## Telemetry flow

1. The daemon clears the transmitter receiver and retransmitter caches.
2. After the cache-cleared response, it periodically requests telemetry.
3. The transmitter collects receiver broadcasts in a bounded table.
4. A multipart telemetry report is serialized over the host UART.
5. The daemon groups parts by report sequence and validates part indexes before
   publishing receiver state.

Telemetry includes receiver identity, link age, battery state, RSSI, uptime,
universe counters, firmware/protocol versions, telemetry sequence, and fail-safe
configuration/state.

Friendly receiver names are host-side aliases and are not part of the embedded
telemetry protocol. The daemon persists them under `[receiver_names]`, keyed by
the receiver's hexadecimal 32-bit ID. This keeps naming independent of firmware
and preserves the hardware ID for targeted management commands.

## Priority and ACK flow

The daemon creates a unique priority ID and sends a marker. The transmitter
marks the next complete host universe, sends priority fragments at the priority
cadence, and receives completion packets from receivers. The transmitter stores
ACK records in a bounded ring and exports them when polled.

The daemon evaluates ACKs per event, receiver, and attempt. A hard-gate event is
complete only when every expected receiver reports
`PRIORITY_COMPLETE_GATE_APPLIED`; an ordinary priority ACK is not sufficient.

Repeated physical ACK records are tracked as duplicate records without turning a
successful logical event into a failure.

## Management-only universe observation

The management transmitter passively listens for ordinary normal-DMX fragments
from the standalone retransmitter; it does not use Wi-Fi promiscuous mode and does
not emit a competing normal-DMX stream. A bounded callback handoff and loop-side
reconstruction accept only complete, structurally valid three-fragment universes.

The daemon polls `0x0A` at approximately 4 Hz in management-only mode. The three
`0x8A` response parts carry a shared sequence, age, source MAC, offset, and
channel bytes. The host publishes the observation only after all parts agree and
are contiguous. UART/control failures affect only the optional display; they do
not stop receiver output, telemetry, or priority control.

The dashboard keeps observed data separate from the editable management universe.
Because the transmitter cannot receive its own ESP-NOW broadcast, its latest local
priority transmission is used as a fallback. A complete retransmitter observation
overrides non-locked channels. When a management-only channel is changed to
`LOCKED`, the current observed value is captured into the local management state;
subsequent retransmitter observations cannot replace it. Explicit management edits
remain permitted on locked channels.

Retransmitter telemetry uses response opcode `0x8B` and is exported alongside the
receiver telemetry poll. The host validates retransmitter identity, magic, packet
length, CRC, and freshness before updating a separate cache; retransmitters are
never represented as receivers. Entries appear in the dashboard only after
discovery. Routine telemetry is best-effort, deterministically scheduled, and
must yield to physical-DMX capture, normal fragments, and control traffic; it
never creates a catch-up burst.

The cache-clear management command clears both device classes atomically from the
operator's perspective. The host drops its receiver and retransmitter references
when the clear is sent and again when the acknowledgement arrives. The
transmitter does the same for its embedded tables and pending telemetry rings.
Retransmitters are reported only while their last telemetry is within the active
offline threshold; an empty report is not a discoverable retransmitter.

The fields include source identity, telemetry sequence, physical-DMX freshness,
learned input slot count, always-enabled input state, locate state, wireless
frames sent, wireless send failures, control generation, and battery. Battery is
`UNKNOWN` for builds without the optional comparator and reports its monitored
state when battery support is compiled in. Production retransmitters operate at
approximately 10 Hz while retaining the normal three-fragment DMX cadence. A
telemetry-only firmware variant exists for scheduler testing and does not
transmit DMX. GPIO2 is the retransmitter locate output; production firmware does
not use it to gate DMX input.

## Fail-safe configuration flow

The daemon sends a mode, timeout, and generation. The transmitter broadcasts a
packed receiver configuration packet. Receivers accept only valid modes and
timeouts, apply the generation, and echo it through telemetry.

Repeated identical configuration packets are idempotent. A receiver does not
clear active fail-safe state or increment its activation counter merely because
the daemon retransmitted the same configuration.
The dashboard output and locate controls use the transmitter's priority
management queue. They are not priority DMX universes; they are higher-priority
control packets sent ahead of normal management and DMX work. Receivers latch
the output override at the final output boundary, so later normal or priority
DMX frames cannot re-enable a disabled line. Disabling output is a visible DMX
interruption and should be treated as a hardware test action; the operator must
explicitly turn it back on.
prepared for the selected receiver's RS-485 line to go silent. The action can
target one receiver ID or all online receivers. Re-enable output explicitly
afterward; a new DMX universe does not implicitly override this manual control.

The locate action is deliberately disruptive. It disables DMX and pulses both
receiver output-related pins for 15 seconds by default. Use it only when the selected
receiver is disconnected from DMX fixtures. The current board has no separate
status LED GPIO; this is a practical identification aid using the existing ESP
module pins, not a non-interrupting locator.

## Failure handling

- Invalid CRC: frame ignored.
- Oversized management payload: parser resynchronizes without allocation growth.
- Full management queue: operation reports failure; normal DMX queue is not
  evicted.
- Lost telemetry: receiver freshness transitions online → stale → offline.
- Lost priority ACK: bounded retry logic may submit another attempt.
- Transmitter reconnect: cache is cleared and runtime receiver configuration is
  resent.

## Implementation checklist for new commands

When adding a management command:

1. Add host constants and a codec function.
2. Add the embedded opcode and packed payload structure.
3. Validate length, bounds, and CRC on the transmitter.
4. Keep handling non-blocking and bounded.
5. Add parser/CRC/round-trip tests.
6. Document queue priority and response semantics here.