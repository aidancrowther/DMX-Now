#!/bin/bash
# Compile/flash the standalone GPIO1/GPIO2 blink diagnostic.
# Usage: ./helpers/flash_gpio_blink.sh [-f] [--port /dev/ttyUSB0]

set -u
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
ARDUINO_CLI="arduino-cli"
PORT="/dev/ttyUSB0"
FLASH=false
SKETCH_DIR="${PROJECT_ROOT}/tests/gpio_blink"
BINARY="${SKETCH_DIR}/build/esp8266.esp8266.generic/gpio_blink.ino.bin"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -f) FLASH=true; shift ;;
        --port)
            [[ $# -ge 2 ]] || { echo "Error: --port requires a value" >&2; exit 1; }
            PORT="$2"; shift 2 ;;
        --port=*) PORT="${1#--port=}"; shift ;;
        --) shift; break ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: $0 [-f] [--port /dev/ttyUSB0]" >&2
            exit 1 ;;
    esac
done

echo "Standalone GPIO1/GPIO2 Blink Diagnostic"
echo "Target board: esp8266:esp8266:generic"
echo "Sketch: ${SKETCH_DIR}"
echo "Serial port: ${PORT}"

if ! "$ARDUINO_CLI" compile -b "esp8266:esp8266:generic" "$SKETCH_DIR" -e; then
    echo "COMPILE FAILED"
    exit 1
fi

echo "COMPILE SUCCESSFUL"
echo "Binary: ${BINARY}"
if [[ "$FLASH" != true ]]; then
    echo "Compilation only. Use -f to compile and flash."
    printf 'Example: %q -f --port %q\n' "$0" "$PORT"
    exit 0
fi

[[ -f "$BINARY" ]] || { echo "FLASH FAILED: binary not found: ${BINARY}" >&2; exit 1; }
esptool --port "$PORT" write-flash 0x0000 "$BINARY"