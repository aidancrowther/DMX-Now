#!/bin/bash

arduino-cli compile -b esp8266:esp8266:generic --library ./libraries/QuickESPNow --library ./libraries/ESP-Dmx ./receiver -e 2>&1 && esptool --port /dev/ttyUSB0 write-flash 0x0000 ./receiver/build/esp8266.esp8266.generic/receiver.ino.bin 2>&1