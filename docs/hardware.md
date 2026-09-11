# Hardware reference

Receivers use an ESP-01/ESP8266, MAX3485 RS-485 transceiver, battery
charging/protection and regulation, and comparator-based low-battery detection.

```text
GPIO1 / UART TX -> MAX3485 DI / DMX data
GPIO2           -> inverted MAX3485 DE control
GPIO3 / UART RX <- active-high low-battery comparator
GPIO0           -> ESP8266 boot/programming use
```

GPIO2 high disables the MAX3485 and GPIO2 low enables it. Firmware keeps the
line disabled during startup and enables it only when initialization and the
configured fail-safe policy permit output.

The current receiver design has no separate controllable status LED. The locate
implementation is therefore deliberately disruptive: it suspends espDMX,
releases GPIO1 from the UART mux, disables the MAX3485 initially, and pulses
both GPIO1 and GPIO2 with a 500 ms half-period for 15 seconds. Driving both
pins accommodates ESP-01 boards whose onboard LED is wired to either commonly
used LED GPIO. GPIO2 is also the MAX3485 enable line, so the pulse pattern
intentionally toggles the RS-485 driver; disconnect the receiver from DMX
fixtures before locating. A future board revision with a dedicated LED GPIO
could provide a non-disruptive locator.

The current design does not provide galvanic USB/DMX isolation. Disconnect a
receiver from DMX equipment before connecting USB charging power. The full
schematic is `Hardware/1-Schematic_ESP DMX.json`.

Receiver modules are programmed separately with:

```bash
./helpers/flash_receiver.sh -f --port <programmer-device>
```

Identify receivers by telemetry identity, not by an assumed USB device number.