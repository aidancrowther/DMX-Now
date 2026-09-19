# Libraries

This directory contains the pinned dependencies and project-owned protocol code
used by DMX Now. Use these bundled copies for reproducible builds; do not replace
them with similarly named Arduino Library Manager versions without revalidating
the firmware.

## Retained dependencies

| Library | Purpose | Current source | Upstream reference | Declared version | Exact project pin |
|---|---|---|---|---:|---|
| QuickESPNow | ESP-NOW transport for ESP8266/ESP32 | [aidancrowther/QuickESPNow](https://github.com/aidancrowther/QuickESPNow) | [gmag11/QuickESPNow](https://github.com/gmag11/QuickESPNow) | `0.8.1` | `27f88ad99e4b58958934c3a3dfabd62ccd338c62` |
| espDMX | ESP8266 physical DMX output | [aidancrowther/espDMX](https://github.com/aidancrowther/espDMX) | [mtongnz/espDMX](https://github.com/mtongnz/espDMX) | v2 | `608ce009edfeebc3bca44b184a9dc667de055284` |
| DMXUART | ESP8266/ESP32 physical DMX input/output UART support | [casesolved-co-uk/DMXUART](https://github.com/casesolved-co-uk/DMXUART) | `4.0.3` | Bundled project copy |
| WirelessDMX | Canonical DMX fragment and management protocol | Project-owned | `1.0.0` | Matching DMX Now source |

The current DMX Now build points at the `aidancrowther` forks until the local
changes are merged upstream, if they are accepted. The original repositories
remain the upstream references. QuickESPNow is three commits ahead of upstream
`main` in the pinned fork, and espDMX is one commit ahead of upstream `master`.
The commit hashes above are authoritative for this project and include the local
changes required by DMX Now.

QuickESPNow is MIT licensed, espDMX is GPL-3.0, and DMXUART is MIT licensed;
see each library directory for the full license text. WirelessDMX is project
code distributed with DMX Now.

## Removed dependency

`LXESP8266DMX` was previously present as a pinned Git dependency but is no longer
used by the active firmware. It has been intentionally removed from this release
layout. The standalone retransmitter uses the bundled `DMXUART` implementation.

## Patches

`patches/` contains retained espDMX patch files documenting earlier compatibility
work. They are reference material unless a future build explicitly applies them.