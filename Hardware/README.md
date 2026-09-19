# Hardware assets

This directory contains the physical design assets for DMX Now receivers and
related hardware.

## Contents

- `3D Models/` — enclosure and mechanical parts used to design and manufacture
  receiver housings. The current models are provided as `.3mf` files and are
  grouped under `3D Models/Receiver Enclosure/`.
- `PCB Files/` — PCB design exports, including the receiver schematic and board
  layout JSON files.

The electrical wiring, GPIO assignments, power precautions, RS-485 topology,
and isolation limitations are documented in [`../Docs/hardware.md`](../Docs/hardware.md).
The firmware and hardware roles are deployment-specific; inspect the schematic
and verify the actual assembled hardware before applying power.

## Current board-design assumptions

The current hardware layouts are intentionally limited to the following board
variants:

- **Receiver:** the receiver PCB layout currently supports only an ESP-01 or
  ESP-01S module.
- **Retransmitter:** the retransmitter PCB design, which has not yet been
  uploaded to this repository, currently supports only a WEMOS Mini Pro. This
  board choice is associated with the retransmitter's external antenna
  requirement.
- **Transmitter:** there is currently no dedicated transmitter PCB design. A
  supported ESP module connected directly through USB provides the required
  transmitter hardware.

Additional board variants may be added in the future, but none are currently
planned. Do not assume that a different ESP8266 module or board form factor is
electrically or mechanically interchangeable without a separate design review.

## Bill of Materials (B.O.M.)

> TODO: Populate and validate the production bill of materials before the first
> hardware release.

| Quantity | Reference / function | Part | Manufacturer | Manufacturer part number | Package | Supplier | Supplier SKU | Notes |
|---:|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | To be populated |

The B.O.M. should eventually include electrical components, connectors,
mechanical hardware, enclosure parts, cables, battery/power components, and
approved substitutions.