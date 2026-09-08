#!/bin/bash
# Feature 7: Build/flash script for the Arduino MEGA DMX refresh-rate monitor.
#
# Usage:
#   ./flash_dmx_monitor.sh                 # compile only
#   ./flash_dmx_monitor.sh -f              # compile + flash (AVR/avrdude)
#   ./flash_dmx_monitor.sh -f --port /dev/ttyUSB1
#
# DMX_USE_PORT1 is passed as a GLOBAL compiler flag (-DDMX_USE_PORT1) so that
# DMXSerial binds USART1 (pins 18/19) for DMX RX while the USB Serial (pins
# 0/1) stays free for telemetry. The flag is added to build.extra_flags, which
# arduino-cli applies to ALL compiled sources including the DMXSerial library
# translation unit (where the port is actually selected). Do NOT rely on a
# #define in the sketch for this -- it would not reach the library's TU.
#
# DMXSerial is resolved from the user sketchbook (~/Arduino/libraries) --
# arduino-cli finds it automatically; it is intentionally NOT pinned to the
# project's ./libraries (this monitor is an AVR target, unrelated to the
# ESP8266 build).
#
# Flashing is done with `arduino-cli upload` (AVR -> avrdude), NOT esptool
# (esptool is for the ESP8266 TX/RX builds only).

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ARDUINO_CLI="arduino-cli"

# Defaults
PORT="/dev/ttyUSB1"
FLASH=false

# Paths
SKETCH_DIR="${SCRIPT_DIR}/tests/dmx_refresh_monitor"
BINARY="${SKETCH_DIR}/build/arduino.avr.mega/dmx_refresh_monitor.ino.hex"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -f)
            FLASH=true
            shift
            ;;
        --port)
            if [[ $# -lt 2 ]]; then
                echo "Error: --port requires a value" >&2
                exit 1
            fi
            PORT="$2"
            shift 2
            ;;
        --port=*)
            PORT="${1#--port=}"
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: $0 [-f] [--port /dev/ttyUSB1]" >&2
            exit 1
            ;;
    esac
done

echo "=============================================="
echo "Feature 7: DMX Refresh Monitor (MEGA 2560)"
echo "Target board: arduino:avr:mega"
echo "Sketch: ${SKETCH_DIR}"
echo "Serial port: ${PORT}"
echo "Flash after compile: ${FLASH}"
echo "Extra flags: -DDMX_USE_PORT1  (DMX on USART1 / pin 19)"
echo "=============================================="

COMPILE_CMD=(
    "$ARDUINO_CLI"
    compile
    -b "arduino:avr:mega"
    --build-property "build.extra_flags=-DDMX_USE_PORT1"
    "$SKETCH_DIR"
    -e
)

if ! "${COMPILE_CMD[@]}"; then
    echo ""
    echo "=============================================="
    echo "COMPILE FAILED"
    echo "=============================================="
    exit 1
fi

echo ""
echo "=============================================="
echo "COMPILE SUCCESSFUL"
echo "=============================================="

if [[ "$FLASH" != true ]]; then
    echo ""
    echo "Compilation only. Use -f to compile and flash."
    printf '  %q -f --port %q\n' "$0" "$PORT"
    echo "=============================================="
    exit 0
fi

echo ""
echo "=============================================="
echo "FLASHING DEVICE (arduino-cli upload / avrdude)"
echo "Port: ${PORT}"
echo "Sketch: ${SKETCH_DIR}"
echo "=============================================="

UPLOAD_CMD=(
    "$ARDUINO_CLI"
    upload
    -b "arduino:avr:mega"
    -p "$PORT"
    "$SKETCH_DIR"
)

if ! "${UPLOAD_CMD[@]}"; then
    echo ""
    echo "=============================================="
    echo "FLASH FAILED"
    echo "=============================================="
    exit 1
fi

echo ""
echo "=============================================="
echo "FLASH SUCCESSFUL"
echo "=============================================="
