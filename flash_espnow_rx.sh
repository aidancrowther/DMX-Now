#!/bin/bash
# Feature 4: Build/flash script for ESP-NOW basic receiver test sketch
#
# Usage:
#   ./flash_espnow_rx.sh
#   ./flash_espnow_rx.sh -f
#   ./flash_espnow_rx.sh -f --port /dev/ttyUSB1
#   ./flash_espnow_rx.sh --port "/dev/ttyUSB1" -f

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ARDUINO_CLI="arduino-cli"

# Defaults
PORT="/dev/ttyUSB0"
FLASH=false

# Paths
LIBRARY_DIR="${SCRIPT_DIR}/libraries/QuickESPNow"
SKETCH_DIR="${SCRIPT_DIR}/tests/espnow_universe_rx"
BINARY="${SKETCH_DIR}/build/esp8266.esp8266.generic/espnow_universe_rx.ino.bin"

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
            echo "Usage: $0 [-f] [--port /dev/ttyUSB0]" >&2
            exit 1
            ;;
    esac
done

echo "=============================================="
echo "Feature 4: ESP-NOW RX Test Sketch"
echo "Target board: esp8266:esp8266:generic"
echo "Library: ${LIBRARY_DIR}"
echo "Sketch: ${SKETCH_DIR}"
echo "Serial port: ${PORT}"
echo "Flash after compile: ${FLASH}"
echo "=============================================="

# Build the command as an array to prevent word splitting or
# interpretation of special characters in paths.
COMPILE_CMD=(
    "$ARDUINO_CLI"
    compile
    -b "esp8266:esp8266:generic"
    --library "$LIBRARY_DIR"
    "$SKETCH_DIR"
    -e
)

# Compile the receiver test sketch
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
echo "Binary: ${BINARY}"
echo "=============================================="

# Stop here unless -f was specified
if [[ "$FLASH" != true ]]; then
    echo ""
    echo "Compilation only. Use -f to compile and flash."
    echo "Example:"
    printf '  %q -f --port %q\n' "$0" "$PORT"
    echo "=============================================="
    exit 0
fi

# Make sure the expected binary actually exists before calling esptool.
if [[ ! -f "$BINARY" ]]; then
    echo ""
    echo "=============================================="
    echo "FLASH FAILED"
    echo "Expected binary not found:"
    echo "  ${BINARY}"
    echo "=============================================="
    exit 1
fi

echo ""
echo "=============================================="
echo "FLASHING DEVICE"
echo "Port: ${PORT}"
echo "Binary: ${BINARY}"
echo "=============================================="

FLASH_CMD=(
    esptool
    --port "$PORT"
    write-flash
    "0x0000"
    "$BINARY"
)

if ! "${FLASH_CMD[@]}"; then
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