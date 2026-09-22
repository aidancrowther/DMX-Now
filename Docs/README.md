# Documentation

The root README is deployment-neutral. These guides contain detailed system,
protocol, hardware, fail-safe, and testing information.

- `architecture.md` — data flow and component responsibilities.
- `daemon.md` — host daemon, configuration, PTY, telemetry, and dashboard.
- Receiver and retransmitter aliases are edited from the dashboard with `n` and
  persisted under `[receiver_names]` in the active TOML configuration.
- `protocol.md` — DMX, priority, management, telemetry, and ACK formats.
- `management-interface.md` — detailed host/transmitter/receiver/retransmitter
  control-plane guide with packet flow diagram.
- `build-flags.md` — firmware compile-time options and test hooks.
- `receiver-failsafe.md` — fail-safe modes, timing, configuration, and recovery.
- `hardware.md` — receiver electronics, pins, power, and programming.
- `retransmitter-deployment.md` — standalone and management-monitored physical-DMX retransmitter deployment.
- `testing.md` — automated, raw-DMX timeout, and generic hardware validation procedures.
- `lab-validation.md` — setup-specific qualification evidence, including the
  completed production retransmitter and 10 Hz extended validation.
- `priority-packet-substantial-completion.md` — priority/gating completion record.