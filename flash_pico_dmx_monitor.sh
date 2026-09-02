#!/bin/bash
# Feature 7: Build/flash the Raspberry Pi Pico DMX refresh monitor.
# DMX input is PIO/DMA on GPIO 1; telemetry uses native USB Serial.

set -eu
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PORT="/dev/ttyACM0"
FLASH=false
SKETCH_DIR="${SCRIPT_DIR}/tests/pico_dmx_refresh_monitor"
FQBN="rp2040:rp2040:rpipico"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -f) FLASH=true; shift ;;
        --port)
            [[ $# -ge 2 ]] || { echo "--port requires a value" >&2; exit 1; }
            PORT="$2"; shift 2 ;;
        --port=*) PORT="${1#--port=}"; shift ;;
        *) echo "Usage: $0 [-f] [--port /dev/ttyACM0]" >&2; exit 1 ;;
    esac
done

echo "=============================================="
echo "Feature 7: DMX Refresh Monitor (Raspberry Pi Pico)"
echo "Target board: ${FQBN}"
echo "Sketch: ${SKETCH_DIR}"
echo "Serial port: ${PORT}"
echo "Flash after compile: ${FLASH}"
echo "DMX input: PIO/DMA GPIO 1"
echo "=============================================="

arduino-cli compile -b "${FQBN}" "${SKETCH_DIR}" -e
echo "COMPILE SUCCESSFUL"

if [[ "${FLASH}" != true ]]; then
    echo "Compilation only. Use -f to compile and flash."
    exit 0
fi

arduino-cli upload -b "${FQBN}" -p "${PORT}" "${SKETCH_DIR}"
echo "FLASH SUCCESSFUL"