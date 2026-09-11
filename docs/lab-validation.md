# Lab validation record

This document records one Linux hardware qualification and is not a required
deployment topology. USB device assignments and monitor wiring are session
specific; receiver identities were discovered from telemetry.

Validated behavior included normal 20 Hz acceptance, priority delivery, hard
gates, receiver removal/reconnection, transmitter reset, daemon restart, PTY
telemetry, priority soak, and receiver `hold`, `blackout`, and
`disable_line` tests.

Fail-safe evidence included a 60-second hold test, a bounded 30-second
blackout test producing a finite all-zero measurement, and a bounded
disable-line test producing zero DMX checks with more than 42 seconds of
no-data. Production transmitter firmware was restored and fresh DMX recovery
passed after each mode.

These results document behavior, not a fixed receiver count, receiver ID set,
USB numbering scheme, or monitor assignment.