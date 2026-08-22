#!/bin/bash
# Feature 4: Flash script for ESP-NOW basic receiver test sketch
# Usage: ./flash_espnow_rx.sh [--port /dev/ttyUSB0]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARDUINO_CLI="arduino-cli"

# Default serial port (adjust for your hardware)
# Allow override via --port argument, otherwise default to /dev/ttyUSB0
PORT="${1:-/dev/ttyUSB0}"

# Parse --port=VALUE argument if provided
if [[ "$PORT" == --port=* ]]; then
  PORT="${PORT#--port=}"
fi

echo "=============================================="
echo "Feature 4: ESP-NOW RX Test Sketch - Flash Script"
echo "Target board: esp8266:esp8266:generic"
echo "Library: $SCRIPT_DIR/libraries/QuickESPNow (local copy)"
echo "Sketch: $SCRIPT_DIR/tests/espnow_basic_rx"
echo "Serial port: $PORT"
echo "=============================================="

# Compile the receiver test sketch
"$ARDUINO_CLI" compile \
  -b esp8266:esp8266:generic \
  --library "$SCRIPT_DIR/libraries/QuickESPNow" \
  "$SCRIPT_DIR/tests/espnow_basic_rx" \
  -e 2>&1

exit_code=$?

if [ $exit_code -ne 0 ]; then
    echo "=============================================="
    echo "COMPILE FAILED"
    echo "=============================================="
    exit 1
fi

echo ""
echo "=============================================="
echo "COMPILE SUCCESSFUL"
echo "Binary: $SCRIPT_DIR/tests/espnow_basic_rx/build/esp8266.esp8266.generic/espnow_basic_rx.ino.bin"
echo "=============================================="
echo ""
echo "To flash, run:"
echo "  esptool --port $PORT write-flash 0x0000 $SCRIPT_DIR/tests/espnow_basic_rx/build/esp8266.esp8266.generic/espnow_basic_rx.ino.bin"
echo ""
echo "Or specify a different port: ./flash_espnow_rx.sh --port /dev/ttyS0"
echo "=============================================="

esptool --port $PORT write-flash 0x0000 ./tests/espnow_basic_rx/build/esp8266.esp8266.generic/espnow_basic_rx.ino.bin