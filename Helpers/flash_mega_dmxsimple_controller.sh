#!/usr/bin/env bash
# Build/flash the USB-controlled Arduino Mega DMX controller using DmxSimple.
#
# Usage:
#   ./Helpers/flash_mega_dmxsimple_controller.sh                 # compile only
#   ./Helpers/flash_mega_dmxsimple_controller.sh -f              # compile + flash
#   ./Helpers/flash_mega_dmxsimple_controller.sh -f --port /dev/ttyUSB1

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
SKETCH_DIR="${PROJECT_ROOT}/Tests/mega_dmxsimple_controller"
PORT="/dev/ttyUSB1"
FLASH=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f)
      FLASH=true
      shift
      ;;
    --port)
      [[ $# -ge 2 ]] || { echo "Error: --port requires a value" >&2; exit 2; }
      PORT="$2"
      shift 2
      ;;
    --port=*)
      PORT="${1#--port=}"
      shift
      ;;
    *)
      echo "Usage: $0 [-f] [--port /dev/ttyUSB1]" >&2
      exit 2
      ;;
  esac
done

arduino-cli compile \
  -b arduino:avr:mega \
  "$SKETCH_DIR" \
  -e

if [[ "$FLASH" == true ]]; then
  arduino-cli upload -b arduino:avr:mega -p "$PORT" "$SKETCH_DIR"
else
  echo "Compilation only. Use -f to flash ${PORT}."
fi