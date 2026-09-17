# System architecture

```text
Art-Net / ENTTEC client -> Linux daemon -> ESP8266 transmitter
                                                |
                                      QuickESPNow wireless transport
                                                |
                                      one or more receivers -> DMX512

An optional management-only transmitter can share the wireless channel with a
standalone physical-DMX re-transmitter. In that deployment the re-transmitter
is the sole source of normal DMX fragments. The management transmitter sends
telemetry/control traffic and explicit priority DMX only; it never emits normal
DMX fragments. The re-transmitter has no host-management dependency and may
continue operating while the management transmitter is offline.
```

The daemon accepts Art-Net or ENTTEC-compatible serial input, normalizes it to
512 channels, and uses bounded latest-state pacing. The transmitter snapshots a
complete universe before fragmentation. Receivers promote only complete,
structurally valid frames and retain the last active universe when fragments or
wireless updates are lost.

In management-only/retransmitter deployments, the management transmitter also
passively receives ordinary DMX fragments on the shared ESP-NOW channel. It
reconstructs complete observations in loop context and exports them as bounded
multipart management responses at a low polling rate. This observer is optional,
read-only, and non-authoritative; it cannot receive its own broadcasts, so locally
sent priority universes provide the display fallback. The daemon preserves local
values on hard-locked channels when applying retransmitter observations.

Priority traffic has separate pacing, targeting, bounded retries, completion
ACKs, and optional atomic channel-gate metadata. Management traffic uses
CRC-protected binary frames on the transmitter UART and bounded multipart
telemetry reports.

Failure boundaries are deliberate: invalid input is rejected, incomplete frames
are abandoned, stale frames cannot regress active output, transmitter loss is
handled by receiver fail-safe policy, and PTY clients may disconnect without
stopping the daemon.