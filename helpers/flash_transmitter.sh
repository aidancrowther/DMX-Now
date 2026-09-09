#!/bin/bash
# Build/flash script for the integrated Wireless DMX transmitter sketch
# (deterministic QuickESPNow DMX broadcast + receiver telemetry reporting).
#
# Usage:
#   ./flash_transmitter.sh
#   ./flash_transmitter.sh -f
#   ./flash_transmitter.sh -f --port /dev/ttyUSB1
#   ./flash_transmitter.sh --port "/dev/ttyUSB1" -f
#
# Compile-only by default; add -f to flash.
# Pins the three required local libraries so the compiler never resolves
# them from ~/Arduino/libraries:
#   - QuickESPNow  (wireless transport)
#   - WirelessDMX  (shared protocol header: wireless_protocol.h)
# 
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
ARDUINO_CLI="arduino-cli"

# Defaults
PORT="/dev/ttyUSB0"
FLASH=false
EXTRA_FLAGS=()   # extra -D defines (e.g. future test hooks)

# Paths
QESPNOW_LIB="${PROJECT_ROOT}/libraries/QuickESPNow"
PROTOCOL_LIB="${PROJECT_ROOT}/libraries/WirelessDMX"
SKETCH_DIR="${PROJECT_ROOT}/transmitter"
BINARY="${SKETCH_DIR}/build/esp8266.esp8266.generic/transmitter.ino.bin"

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

        --define)
            if [[ $# -lt 2 ]]; then
                echo "Error: --define requires a value" >&2
                exit 1
            fi

            EXTRA_FLAGS+=("$2")
            shift 2
            ;;

        --define=*)
            EXTRA_FLAGS+=("${1#--define=}")
            shift
            ;;

        --)
            shift
            break
            ;;

        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: $0 [-f] [--port /dev/ttyUSB0] [--define -DEXTRA]" >&2
            exit 1
            ;;
    esac
done

echo "=============================================="
echo "Integrated Wireless DMX Transmitter"
echo "Target board: esp8266:esp8266:generic"
echo "Libraries:"
echo "  QuickESPNow: ${QESPNOW_LIB}"
echo "  WirelessDMX: ${PROTOCOL_LIB}"
echo "Sketch: ${SKETCH_DIR}"
echo "Serial port: ${PORT}"
echo "Flash after compile: ${FLASH}"
if [[ ${#EXTRA_FLAGS[@]} -gt 0 ]]; then
    echo "Extra defines: ${EXTRA_FLAGS[*]}"
fi
echo "=============================================="

# Build the command as an array to prevent word splitting or
# interpretation of special characters in paths.
COMPILE_CMD=(
    "$ARDUINO_CLI"
    compile
    -b "esp8266:esp8266:generic"
    --library "$QESPNOW_LIB"
    --library "$PROTOCOL_LIB"
)
if [[ ${#EXTRA_FLAGS[@]} -gt 0 ]]; then
    COMPILE_CMD+=( --build-property "build.extra_flags= ${EXTRA_FLAGS[*]}" )
fi
COMPILE_CMD+=( "$SKETCH_DIR" -e )

# Compile the integrated transmitter sketch
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
