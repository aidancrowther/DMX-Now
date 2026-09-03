#!/usr/bin/env bash
# Feature 8 Mega DMX monitor: DMX on USART1/pin 19, USB control on ttyUSB1.
set -euo pipefail
port=/dev/ttyUSB1; flash=false
while (($#)); do case "$1" in -f) flash=true;; --port) port=$2; shift;; --port=*) port="${1#*=}";; *) echo "Usage: $0 [-f] [--port /dev/ttyUSB1]" >&2; exit 2;; esac; shift; done
arduino-cli compile -b arduino:avr:mega --build-property build.extra_flags=-DDMX_USE_PORT1 tests/enttec_dmx_monitor -e
if $flash; then arduino-cli upload -b arduino:avr:mega -p "$port" tests/enttec_dmx_monitor; fi
