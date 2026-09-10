# Receiver fail-safe behavior

## Modes

- `hold`: retain the last complete universe; this is the default.
- `blackout`: output a complete zero universe after timeout while keeping the
  RS-485 line active.
- `disable_line`: disable the MAX3485 driver after timeout.

The daemon default is 60 seconds. Runtime values are validated from 30 through
3600 seconds. Compile-time receiver defaults may be overridden, but runtime
settings are not persisted in receiver flash.

The loss timer is refreshed only by a complete promoted normal or priority
universe. Fragments, malformed/stale packets, telemetry, and configuration
packets do not refresh it.

A new complete universe recovers the output. For `disable_line`, the fresh
universe is loaded before the line is re-enabled. Repeated identical
configuration packets are idempotent and do not clear active fail-safe state or
increment activation counters repeatedly.

The daemon sends a generation with the runtime configuration and confirms it
through telemetry. Receivers boot with compile-time defaults until the daemon
reapplies its current generation.