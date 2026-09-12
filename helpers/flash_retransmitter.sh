#!/bin/bash
# Compile/flash the UART0 DMX -> ESP-NOW retransmitter.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
ARDUINO_CLI="arduino-cli"
PORT="/dev/ttyUSB0"
FLASH=false
MENUCONFIG=false
EXTRA_FLAGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            cat <<'EOF'
Usage: flash_retransmitter.sh [-f] [--port PORT] [--channel N] [--universe N]
                              [--rate HZ] [--accept-partial] [--menuconfig]
                              [--define DEFINE]

Compile-only is the default. Use -f to flash after compiling.

Options:
  --channel N         ESP-NOW channel (default: 1).
  --universe N        Wireless universe ID (default: 1).
  --rate HZ           Wireless refresh rate (default: 20 Hz).
  --accept-partial    Accept shorter DMX frames and zero-fill through channel 512.
  --menuconfig        Prompt for all retransmitter build options.
  --define DEFINE     Add an extra compiler definition.
  --port PORT         ESP8266 programming port when -f is used.
  -f                  Flash after compiling.
EOF
            exit 0
            ;;
        -f) FLASH=true; shift ;;
        --port) [[ $# -ge 2 ]] || { echo "--port requires a value" >&2; exit 2; }; PORT="$2"; shift 2 ;;
        --port=*) PORT="${1#--port=}"; shift ;;
        --channel) [[ $# -ge 2 ]] || { echo "--channel requires a value" >&2; exit 2; }; EXTRA_FLAGS+=("-DRETRANSMITTER_ESPNOW_CHANNEL=$2"); shift 2 ;;
        --channel=*) EXTRA_FLAGS+=("-DRETRANSMITTER_ESPNOW_CHANNEL=${1#--channel=}"); shift ;;
        --universe) [[ $# -ge 2 ]] || { echo "--universe requires a value" >&2; exit 2; }; EXTRA_FLAGS+=("-DRETRANSMITTER_UNIVERSE_ID=$2"); shift 2 ;;
        --universe=*) EXTRA_FLAGS+=("-DRETRANSMITTER_UNIVERSE_ID=${1#--universe=}"); shift ;;
        --rate) [[ $# -ge 2 ]] || { echo "--rate requires a value" >&2; exit 2; }; EXTRA_FLAGS+=("-DRETRANSMITTER_WIRELESS_REFRESH_HZ=$2"); shift 2 ;;
        --rate=*) EXTRA_FLAGS+=("-DRETRANSMITTER_WIRELESS_REFRESH_HZ=${1#--rate=}"); shift ;;
        --accept-partial) EXTRA_FLAGS+=("-DRETRANSMITTER_ACCEPT_PARTIAL_UNIVERSE=1"); shift ;;
        --define) [[ $# -ge 2 ]] || { echo "--define requires a value" >&2; exit 2; }; EXTRA_FLAGS+=("$2"); shift 2 ;;
        --define=*) EXTRA_FLAGS+=("${1#--define=}"); shift ;;
        --menuconfig) MENUCONFIG=true; shift ;;
        --) shift; break ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [[ "$MENUCONFIG" == true ]]; then
    read -r -p "ESP-NOW channel [1]: " value; value=${value:-1}; EXTRA_FLAGS+=("-DRETRANSMITTER_ESPNOW_CHANNEL=$value")
    read -r -p "Universe ID [1]: " value; value=${value:-1}; EXTRA_FLAGS+=("-DRETRANSMITTER_UNIVERSE_ID=$value")
    read -r -p "Wireless rate Hz [20]: " value; value=${value:-20}; EXTRA_FLAGS+=("-DRETRANSMITTER_WIRELESS_REFRESH_HZ=$value")
    read -r -p "TX drain timeout ms [100]: " value; value=${value:-100}; EXTRA_FLAGS+=("-DRETRANSMITTER_TX_DRAIN_TIMEOUT_MS=$value")
    read -r -p "TX overhead ms [27]: " value; value=${value:-27}; EXTRA_FLAGS+=("-DRETRANSMITTER_TX_OVERHEAD_MS=$value")
    read -r -p "Accept partial DMX universes? [y/N]: " value
    case "${value,,}" in
        y|yes) EXTRA_FLAGS+=("-DRETRANSMITTER_ACCEPT_PARTIAL_UNIVERSE=1") ;;
        *) : ;;
    esac
fi

QESPNOW_LIB="${PROJECT_ROOT}/libraries/QuickESPNow"
PROTOCOL_LIB="${PROJECT_ROOT}/libraries/WirelessDMX"
INPUT_LIB="${PROJECT_ROOT}/libraries/LXESP8266DMX"
SKETCH_DIR="${PROJECT_ROOT}/retransmitter"
BINARY="${SKETCH_DIR}/build/esp8266.esp8266.generic/retransmitter.ino.bin"
CMD=("$ARDUINO_CLI" compile -b esp8266:esp8266:generic --library "$QESPNOW_LIB" --library "$PROTOCOL_LIB" --library "$INPUT_LIB")
if [[ ${#EXTRA_FLAGS[@]} -gt 0 ]]; then CMD+=(--build-property "build.extra_flags= ${EXTRA_FLAGS[*]}"); fi
CMD+=("$SKETCH_DIR" -e)
echo "Retransmitter compile: ${EXTRA_FLAGS[*]:-defaults}"
"${CMD[@]}"
if [[ "$FLASH" != true ]]; then exit 0; fi
[[ -f "$BINARY" ]] || { echo "Expected binary not found: $BINARY" >&2; exit 1; }
esptool --port "$PORT" write-flash 0x0000 "$BINARY"