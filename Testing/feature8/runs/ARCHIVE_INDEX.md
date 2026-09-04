# Feature 8 evidence index

## Canonical evidence

The following directories contain the final evidence referenced by the Feature
8 test plan:

1. `canonical/00_deployment/` — final transmitter and Mega deployment logs.
2. `canonical/01_final_production_smoke/` — final 4/4 production smoke run.
3. `canonical/02_parser_edge_cases/` — 13/13 parser and boundary cases.
4. `canonical/03_delivery_load/` — corrected 3/3 delivery/load cases.
5. `canonical/04_fragment_faults/` — seven fragment fault cases.
6. `canonical/05_sequence_wrap/` — sequence rollover smoke run.
7. `canonical/06_soak_30min/` — verified 30-minute production soak.

Every canonical manifest reports `passed: true`. The canonical runs used
`/dev/ttyUSB0` for the transmitter and `/dev/ttyUSB1` for the Arduino Mega;
`/dev/ttyUSB2` was not used.

## Archived evidence

`archive/` contains superseded smoke and edge-case repetitions, intermediate
deployment/recovery runs, the first delivery/load run with the incorrect
measurement oracle, and the earlier soak runs that completed the timed window
but could not capture the final `RESULT` line. They are retained for
traceability but are not acceptance evidence.

Compile-only logs are in `../results/archive/`.

Generated Python `__pycache__` files and duplicate console copies of manifests
were intentionally removed during cleanup.