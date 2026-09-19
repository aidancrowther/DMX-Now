#!/bin/bash
# Build/flash script for the integrated Wireless DMX transmitter sketch
# (deterministic QuickESPNow DMX broadcast + receiver telemetry reporting).
#
# Usage:
#   ./flash_transmitter.sh
#   ./flash_transmitter.sh -f
#   ./flash_transmitter.sh -f --port /dev/ttyUSB1
#   ./flash_transmitter.sh --d1 -f
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
ROLE="bridge"
BOARD="esp8266:esp8266:generic"
BOARD_BUILD="esp8266.esp8266.generic"

# Paths
QESPNOW_LIB="${PROJECT_ROOT}/Libraries/QuickESPNow"
PROTOCOL_LIB="${PROJECT_ROOT}/Libraries/WirelessDMX"
SKETCH_DIR="${PROJECT_ROOT}/Firmware/Transmitter"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            cat <<'EOF'
Usage: flash_transmitter.sh [OPTIONS]

Compile the integrated ESP8266 transmitter. Compilation is the default;
use -f to flash after compiling.

Options:
  -f                         Flash the compiled image.
  --port PORT                ESP8266 programming port (default: /dev/ttyUSB0).
  --d1                       Target a Wemos D1 Mini/Pro instead of ESP-01.
  --bridge                   Runtime-switchable bridge-capable image (default).
  --management-only          Lock image to management-only behavior.
  --lock-bridge              Lock runtime role to bridge.
  --lock-management-only     Lock runtime role to management-only.
  --define DEFINE            Add an extra compiler definition.
  -h, --help                 Show this help.

Runtime-capable images can be switched by the daemon through the management
protocol. Locked images reject incompatible role requests.
EOF
            exit 0
            ;;
        -f)
            FLASH=true
            shift
            ;;

        --d1)
            BOARD="esp8266:esp8266:d1_mini"
            BOARD_BUILD="esp8266.esp8266.d1_mini"
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

        --management-only)
            ROLE="management-only"
            EXTRA_FLAGS+=("-DTRANSMITTER_MANAGEMENT_ONLY")
            shift
            ;;

        --bridge)
            ROLE="bridge"
            shift
            ;;

        --lock-bridge)
            ROLE="locked-bridge"
            EXTRA_FLAGS+=("-DTRANSMITTER_LOCK_BRIDGE")
            shift
            ;;

        --lock-management-only)
            ROLE="locked-management-only"
            EXTRA_FLAGS+=("-DTRANSMITTER_LOCK_MANAGEMENT_ONLY")
            shift
            ;;

        --)
            shift
            break
            ;;

        *)
            echo "Unknown argument: $1" >&2
            echo "Usage: $0 [-f] [--d1] [--bridge|--management-only|--lock-bridge|--lock-management-only] [--port /dev/ttyUSB0] [--define -DEXTRA]" >&2
            exit 1
            ;;
    esac
done

BINARY="${SKETCH_DIR}/build/${BOARD_BUILD}/Transmitter.ino.bin"

echo "=============================================="
echo "Integrated Wireless DMX Transmitter"
echo "Target board: ${BOARD}"
echo "Libraries:"
echo "  QuickESPNow: ${QESPNOW_LIB}"
echo "  WirelessDMX: ${PROTOCOL_LIB}"
echo "Sketch: ${SKETCH_DIR}"
echo "Serial port: ${PORT}"
echo "Flash after compile: ${FLASH}"
echo "Role: ${ROLE}"
if [[ ${#EXTRA_FLAGS[@]} -gt 0 ]]; then
    echo "Extra defines: ${EXTRA_FLAGS[*]}"
fi
echo "=============================================="

# Build the command as an array to prevent word splitting or
# interpretation of special characters in paths.
COMPILE_CMD=(
    "$ARDUINO_CLI"
    compile
    -b "$BOARD"
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