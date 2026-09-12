#!/bin/bash
# Compile the retransmitter end-to-end Mega generator/monitor.
# This helper is compile-only by default. Hardware flashing is intentionally
# not performed by the feature setup workflow.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
SKETCH_DIR="${PROJECT_ROOT}/tests/retransmitter_end_to_end"
ARDUINO_CLI="arduino-cli"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    echo "Usage: $0"
    echo "Compile-only helper for the Mega retransmitter E2E generator/monitor."
    echo "Uses DMX_USE_PORT1: Mega USART1 generates DMX; USB Serial carries commands/results."
    echo "Flashing is deliberately not supported by this setup helper."
    exit 0
fi
if [[ $# -ne 0 ]]; then
    echo "No arguments are supported; this helper is compile-only." >&2
    exit 2
fi

"$ARDUINO_CLI" compile \
    -b arduino:avr:mega \
    --build-property build.extra_flags=-DDMX_USE_PORT1 \
    "$SKETCH_DIR" -e