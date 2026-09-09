#!/usr/bin/env bash
# Feature 8 Mega DMX monitor: DMX on USART1/pin 19, USB control on ttyUSB1.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
port=/dev/ttyUSB1; flash=false
while (($#)); do case "$1" in -f) flash=true;; --port) port=$2; shift;; --port=*) port="${1#*=}";; *) echo "Usage: $0 [-f] [--port /dev/ttyUSB1]" >&2; exit 2;; esac; shift; done
SKETCH_DIR="${PROJECT_ROOT}/tests/enttec_dmx_monitor"
arduino-cli compile -b arduino:avr:mega --build-property build.extra_flags=-DDMX_USE_PORT1 "$SKETCH_DIR" -e
if $flash; then arduino-cli upload -b arduino:avr:mega -p "$port" "$SKETCH_DIR"; fi
