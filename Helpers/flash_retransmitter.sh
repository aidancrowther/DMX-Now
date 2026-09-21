#!/bin/bash
# Compile/flash the UART0 DMX -> ESP-NOW retransmitter.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
ARDUINO_CLI="arduino-cli"
PORT="/dev/ttyUSB0"
FLASH=false
MENUCONFIG=false
PRODUCTION=false
EXTRA_FLAGS=()
BOARD="esp8266:esp8266:generic"
BOARD_BUILD="esp8266.esp8266.generic"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            cat <<'EOF'
Usage: flash_retransmitter.sh [-f] [--production] [--d1] [--port PORT] [--channel N] [--universe N]
                              [--rate HZ] [--menuconfig]
                              [--define DEFINE]

Compile-only is the default. Use -f to flash after compiling.

Options:
  --channel N         ESP-NOW channel (default: 1).
  --universe N        Wireless universe ID (default: 1).
  --rate HZ           Wireless refresh rate (default: 10 Hz).
  --d1                Target a WEMOS D1 Mini/Pro-compatible board.
  --production        Build the normal DMX retransmitter with telemetry enabled (default).
  --telemetry-only    Disable DMX input and fragment transmission; send telemetry only.
  --receiver-control  Enable GPIO2 receiver /RE control (default).
  --no-receiver-control  Disable receiver /RE control.
  --battery-monitor   Enable the GPIO1 battery comparator input.
  --no-battery-monitor  Disable battery monitoring (default).
  --battery-low-active-high  Treat HIGH comparator output as battery-low.
  --menuconfig        Prompt for all retransmitter build options.
  --define DEFINE     Add an extra compiler definition.
  --port PORT         ESP8266 programming port when -f is used.
  -f                  Flash after compiling.
EOF
            exit 0
            ;;
        -f) FLASH=true; shift ;;
        --d1)
            BOARD="esp8266:esp8266:d1_mini"
            BOARD_BUILD="esp8266.esp8266.d1_mini"
            shift
            ;;
        --telemetry-only)
            EXTRA_FLAGS+=("-DRETRANSMITTER_TELEMETRY_ONLY=1")
            shift
            ;;
        --production)
            PRODUCTION=true
            shift
            ;;
        --receiver-control)
            EXTRA_FLAGS+=("-DRETRANSMITTER_DMX_INPUT_ENABLE_PIN=2")
            shift
            ;;
        --no-receiver-control)
            EXTRA_FLAGS+=("-DRETRANSMITTER_DMX_INPUT_ENABLE_PIN=-1")
            shift
            ;;
        --battery-monitor)
            EXTRA_FLAGS+=("-DRETRANSMITTER_BATTERY_MONITOR=1")
            shift
            ;;
        --no-battery-monitor)
            EXTRA_FLAGS+=("-DRETRANSMITTER_BATTERY_MONITOR=0")
            shift
            ;;
        --battery-low-active-high)
            EXTRA_FLAGS+=("-DRETRANSMITTER_BATTERY_LOW_ACTIVE_LOW=0")
            shift
            ;;
        --port) [[ $# -ge 2 ]] || { echo "--port requires a value" >&2; exit 2; }; PORT="$2"; shift 2 ;;
        --port=*) PORT="${1#--port=}"; shift ;;
        --channel) [[ $# -ge 2 ]] || { echo "--channel requires a value" >&2; exit 2; }; EXTRA_FLAGS+=("-DRETRANSMITTER_ESPNOW_CHANNEL=$2"); shift 2 ;;
        --channel=*) EXTRA_FLAGS+=("-DRETRANSMITTER_ESPNOW_CHANNEL=${1#--channel=}"); shift ;;
        --universe) [[ $# -ge 2 ]] || { echo "--universe requires a value" >&2; exit 2; }; EXTRA_FLAGS+=("-DRETRANSMITTER_UNIVERSE_ID=$2"); shift 2 ;;
        --universe=*) EXTRA_FLAGS+=("-DRETRANSMITTER_UNIVERSE_ID=${1#--universe=}"); shift ;;
        --rate) [[ $# -ge 2 ]] || { echo "--rate requires a value" >&2; exit 2; }; EXTRA_FLAGS+=("-DRETRANSMITTER_WIRELESS_REFRESH_HZ=$2"); shift 2 ;;
        --rate=*) EXTRA_FLAGS+=("-DRETRANSMITTER_WIRELESS_REFRESH_HZ=${1#--rate=}"); shift ;;
        --define) [[ $# -ge 2 ]] || { echo "--define requires a value" >&2; exit 2; }; EXTRA_FLAGS+=("$2"); shift 2 ;;
        --define=*) EXTRA_FLAGS+=("${1#--define=}"); shift ;;
        --menuconfig) MENUCONFIG=true; shift ;;
        --) shift; break ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

for define in "${EXTRA_FLAGS[@]}"; do
    if [[ "$define" == "-DRETRANSMITTER_TELEMETRY_ONLY=1" && "$PRODUCTION" == true ]]; then
        echo "--production and --telemetry-only are mutually exclusive" >&2
        exit 2
    fi
done

if [[ "$MENUCONFIG" == true ]]; then
    read -r -p "ESP-NOW channel [1]: " value; value=${value:-1}; EXTRA_FLAGS+=("-DRETRANSMITTER_ESPNOW_CHANNEL=$value")
    read -r -p "Universe ID [1]: " value; value=${value:-1}; EXTRA_FLAGS+=("-DRETRANSMITTER_UNIVERSE_ID=$value")
    read -r -p "Wireless rate Hz [10]: " value; value=${value:-10}; EXTRA_FLAGS+=("-DRETRANSMITTER_WIRELESS_REFRESH_HZ=$value")
    read -r -p "TX drain timeout ms [100]: " value; value=${value:-100}; EXTRA_FLAGS+=("-DRETRANSMITTER_TX_DRAIN_TIMEOUT_MS=$value")
    read -r -p "TX overhead ms [27]: " value; value=${value:-27}; EXTRA_FLAGS+=("-DRETRANSMITTER_TX_OVERHEAD_MS=$value")
    read -r -p "Enable receiver /RE control on GPIO2? [Y/n]: " value
    if [[ "${value,,}" != "n" && "${value,,}" != "no" ]]; then
        EXTRA_FLAGS+=("-DRETRANSMITTER_DMX_INPUT_ENABLE_PIN=2")
    else
        EXTRA_FLAGS+=("-DRETRANSMITTER_DMX_INPUT_ENABLE_PIN=-1")
    fi
    read -r -p "Enable battery comparator monitoring on GPIO1? [y/N]: " value
    if [[ "${value,,}" == "y" || "${value,,}" == "yes" ]]; then
        EXTRA_FLAGS+=("-DRETRANSMITTER_BATTERY_MONITOR=1")
        read -r -p "Battery-low comparator active low? [Y/n]: " value
        if [[ "${value,,}" == "n" || "${value,,}" == "no" ]]; then
            EXTRA_FLAGS+=("-DRETRANSMITTER_BATTERY_LOW_ACTIVE_LOW=0")
        else
            EXTRA_FLAGS+=("-DRETRANSMITTER_BATTERY_LOW_ACTIVE_LOW=1")
        fi
    else
        EXTRA_FLAGS+=("-DRETRANSMITTER_BATTERY_MONITOR=0")
    fi
fi

QESPNOW_LIB="${PROJECT_ROOT}/Libraries/QuickESPNow"
PROTOCOL_LIB="${PROJECT_ROOT}/Libraries/WirelessDMX"
INPUT_LIB="${PROJECT_ROOT}/Libraries/DMXUART"
SKETCH_DIR="${PROJECT_ROOT}/Firmware/ReTransmitter"
BUILD_MODE="partial"
for define in "${EXTRA_FLAGS[@]}"; do
    case "$define" in
        -DRETRANSMITTER_DIAGNOSTICS=1) BUILD_MODE="partial-diagnostic" ;;
        -DRETRANSMITTER_TELEMETRY_ONLY=1) BUILD_MODE="telemetry-only" ;;
    esac
done
BUILD_DIR="${SKETCH_DIR}/build/${BOARD_BUILD}/${BUILD_MODE}"
BINARY="${BUILD_DIR}/ReTransmitter.ino.bin"
# Rebuild from a clean sketch cache every time so the sole partial-mode image is
# always derived from the current source and pinned libraries.
CMD=("$ARDUINO_CLI" compile --clean --build-path "$BUILD_DIR" -b "$BOARD" --library "$QESPNOW_LIB" --library "$PROTOCOL_LIB" --library "$INPUT_LIB")
if [[ ${#EXTRA_FLAGS[@]} -gt 0 ]]; then CMD+=(--build-property "build.extra_flags= ${EXTRA_FLAGS[*]}"); fi
CMD+=("$SKETCH_DIR" -e)
echo "Retransmitter compile: ${EXTRA_FLAGS[*]:-defaults}"
echo "Target board: ${BOARD}"
echo "Build mode: ${BUILD_MODE}"
echo "Build directory: ${BUILD_DIR}"
"${CMD[@]}"
if [[ "$FLASH" != true ]]; then exit 0; fi
[[ -f "$BINARY" ]] || { echo "Expected binary not found: $BINARY" >&2; exit 1; }
echo "Binary SHA-256: $(sha256sum "$BINARY" | awk '{print $1}')"
esptool --port "$PORT" write-flash 0x0000 "$BINARY"