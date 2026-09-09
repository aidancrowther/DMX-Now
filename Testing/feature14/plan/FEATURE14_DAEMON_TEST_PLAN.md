# Feature 14 Daemon-Level Priority Transmission

## Current status

The daemon-only stage is substantially implemented. It provides an explicit
priority path without changing the deployed transmitter or receiver firmware.
Priority submissions currently use the existing complete-universe DMX packet
format, but are scheduled ahead of normal pending traffic by the host daemon.

## Implemented behavior

* Manual 512-channel universe buffer in the daemon service.
* Per-channel value editing API with validation for channels 1–512 and values
  0–255.
* Complete-universe manual send API.
* Normal and high-priority manual transmission modes.
* Bounded priority queue, default capacity four events.
* Priority repeat count and TTL validation.
* Priority ID and bounded diagnostic reason.
* Lead-in and lead-out dead-time states.
* Latest-state normal traffic retained while priority is active.
* Priority queue overflow rejection.
* Priority expiry and cancellation.
* Normal-traffic starvation protection through bounded event bursts.
* Priority counters and dashboard status.
* Manual dashboard screen with per-channel editing, full-universe view, normal
  or priority mode, repeat/TTL controls, send, and clear operations.

## Dashboard controls

From the main dashboard:

```text
u       open Manual DMX
```

Manual DMX screen:

```text
Up/Down/j/k   select channel
Left/Right    move by ten channels
e             edit selected channel value
+/-           increment/decrement selected value
n             normal mode
p             high-priority mode
r             cycle repeat count
t             cycle TTL
Enter         send complete universe
c             clear manual universe
u             toggle full-universe view
x             return to dashboard
```

Priority mode is visibly marked as high priority and warns that the bounded
priority scheduler is being used.

## Current protocol limitation

Receiver-confirmed delivery is not enabled yet. Existing receiver firmware does
not recognize a separate priority packet type or send priority completion ACKs.
The current implementation therefore confirms only daemon-side submission.

The daemon does not claim that a priority event reached every receiver until
the receiver-aware firmware stage has been implemented and validated.

## Receiver flashing checkpoint

No receiver flashing is required for the current daemon-only stage.

Receiver flashing becomes required when the following are implemented:

* New priority DMX fragment packet type.
* Receiver priority reconstruction state.
* Priority completion packet.
* Deterministic 32-slot ACK scheduling.
* Receiver-confirmed daemon state.

At that checkpoint, the transmitter and every receiver must be updated as a
coordinated deployment. The implementation process will stop and request
confirmation before flashing receiver hardware.

## Automated tests

The daemon test suite covers priority configuration, manual channel editing,
repeat/lead timing, queue behavior, and normal service integration.

## Live daemon test

The current daemon-level implementation was tested with the real transmitter at
`/dev/ttyUSB0` and two active receivers. A manual priority universe was sent
with three repetitions; the daemon reported three priority frames submitted,
returned to idle with result `submitted`, and continued receiving telemetry from
both receivers.

This validates daemon scheduling and transmitter submission, not receiver ACK
confirmation.