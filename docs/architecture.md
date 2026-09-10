# System architecture

```text
Art-Net / ENTTEC client -> Linux daemon -> ESP8266 transmitter
                                                |
                                      QuickESPNow wireless transport
                                                |
                                      one or more receivers -> DMX512
```

The daemon accepts Art-Net or ENTTEC-compatible serial input, normalizes it to
512 channels, and uses bounded latest-state pacing. The transmitter snapshots a
complete universe before fragmentation. Receivers promote only complete,
structurally valid frames and retain the last active universe when fragments or
wireless updates are lost.

Priority traffic has separate pacing, targeting, bounded retries, completion
ACKs, and optional atomic channel-gate metadata. Management traffic uses
CRC-protected binary frames on the transmitter UART and bounded multipart
telemetry reports.

Failure boundaries are deliberate: invalid input is rejected, incomplete frames
are abandoned, stale frames cannot regress active output, transmitter loss is
handled by receiver fail-safe policy, and PTY clients may disconnect without
stopping the daemon.