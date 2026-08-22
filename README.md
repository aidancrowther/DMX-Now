# ESP8266 Wireless DMX

Experimental wireless DMX512 system using ESP8266 modules, QuickESPNow, and MAX3485 RS-485 transceivers.

The system uses a PC-connected ESP8266 transmitter to receive DMX universe data and broadcast it wirelessly to multiple battery-powered ESP-01 receivers. Each receiver maintains the last complete wireless universe and continuously regenerates a normal wired DMX512 signal for its attached fixture or DMX chain.

The project is being developed incrementally. For espDMX hardware output, compilation success implies hardware validation; for QuickESPNow wireless transport, compilation verification does not imply link budget or throughput validation.

## Core Design

The intended data path is:

```
PC lighting software
        |
        | ENTTEC DMX USB Pro-compatible serial protocol
        v
ESP8266 transmitter
        |
        | latest universe buffer
        |
        | configurable refresh rate
        v
QuickESPNow broadcast
        |
   +----+----+---------+
   |         |         |
   v         v         v
ESP-01    ESP-01    ESP-01
receiver  receiver  receiver
   |         |         |
MAX3485   MAX3485   MAX3485
   |         |         |
  DMX       DMX       DMX
   |         |         |
fixture   fixture   fixture
```

The wireless transport is intentionally a latest-state system rather than a guaranteed-delivery stream.

If a wireless update is missed, receivers continue outputting their previous complete universe until a newer complete universe arrives.

## Development Approach

Develop this project as a series of small, independently testable features.

Do not attempt to implement the entire system in one pass.

Each feature should:

1. Have a narrow scope.
2. Compile before moving on.
3. Avoid unrelated refactoring.
4. Preserve previously working functionality.
5. Clearly distinguish compile-tested behavior from hardware-tested behavior.
6. Leave TODO comments where hardware verification is required.

When working on a requested feature, stop when that feature is complete unless explicitly instructed to continue.

## Working Directory

All development work must remain within the current project directory.

Do not use `/tmp`, `/var/tmp`, or another external directory for drafting or development.

If temporary working files are required, use a local directory such as:

```
./.work/
```

or:

```
./tmp/
```

This allows development activity to be monitored while the coding agent is working.

## Toolchain

Use the Arduino ESP8266 framework.

Do not use PlatformIO.

Use `arduino-cli` for compilation verification.

ESP8266 Arduino board package:

```
http://arduino.esp8266.com/stable/package_esp8266com_index.json
```

Receiver board target:

```
esp8266:esp8266:generic
```

This corresponds to the Generic ESP8266 Module target and is suitable for the ESP-01.

Before adding board-specific FQBN options, inspect the installed options with:

```
arduino-cli board details -b esp8266:esp8266:generic
```

ESP-01 modules may have different flash capacities, so do not assume a particular flash-size option unless established for the hardware being used.

## Required Libraries

### QuickESPNow

Repository:

```
https://github.com/gmag11/QuickESPNow
```

QuickESPNow MUST be obtained directly from this GitHub repository.

Do not install or substitute a version from Arduino Library Manager.

Preferred local location:

```
./libraries/QuickESPNow/
```

The checked-out source should be inspected before using its API.

Record the Git commit used for development in this README once installed.

QuickESPNow is responsible for wireless communication between the transmitter and receivers.

The ESP8266 implementation is documented as providing approximately 200 kbps of practical throughput. Do not assume this bandwidth is guaranteed.

### espDMX

Repository:

```
https://github.com/mtongnz/espDMX
```

espDMX MUST be obtained directly from this GitHub repository.

Do not install or substitute a version from Arduino Library Manager.

Preferred local location:

```
./libraries/espDMX/
```

espDMX is responsible for generating the physical DMX512 output from receiver ESP8266 modules.

Inspect the checked-out source and examples before using its API.

Record the Git commit used for development in this README once installed.

The espDMX library uses pre-declared global instances (`dmxA`, `dmxB`) — instantiate locally to avoid conflicts with the upstream globals (we use `dmxA` on UART0/GPIO1).

## Receiver Hardware

Each receiver is intended to contain:

* ESP-01 / ESP8266
* MAX3485 3.3 V RS-485 transceiver
* 1-cell Li-ion/LiPo battery
* TP4056 charging/protection module
* 3.3 V buck/boost regulator
* LM358 low-battery comparator
* LM385Z-1.2 voltage reference
* 10 kΩ trim pot for low-battery threshold
* 2N2222 transistor for MAX3485 driver-enable inversion
* DMX transient protection
* appropriate decoupling/bulk capacitance

ESP-01 modules are socketed and will be removed from the receiver for programming.

There is no requirement for in-circuit programming.

## Receiver Pin Allocation

The intended ESP-01 pin allocation is fixed unless a hardware issue requires changing it:

```
GPIO1 / UART TX -> DMX data / MAX3485 DI

GPIO2           -> MAX3485 DE control
                   through inverting 2N2222 stage

GPIO3 / UART RX <- digital low-battery signal

GPIO0           -> reserved for normal ESP8266
                   boot requirements
```

GPIO3 does not need to remain available for programming because the ESP-01 will be physically removed and programmed separately.

## MAX3485 Driver Enable

GPIO2 controls MAX3485 DE through an inverting 2N2222 stage.

Hardware behavior:

```
GPIO2 HIGH
    -> 2N2222 ON
    -> MAX3485 DE LOW
    -> DMX transmitter disabled

GPIO2 LOW
    -> 2N2222 OFF
    -> MAX3485 DE pulled HIGH
    -> DMX transmitter enabled
```

This is intentional.

GPIO2 must be HIGH for normal ESP8266 boot, so the hardware arrangement ensures that the MAX3485 remains disabled during ESP startup.

Firmware must not enable DMX output until initialization is complete.

## Battery System

Receivers are battery powered during operation.

Current design:

```
1S LiPo
   |
TP4056
charger/protection
   |
3.3 V buck/boost
   |
   +---- ESP-01
   |
   +---- MAX3485
   |
   +---- supporting circuitry
```

Charging isolation is NOT currently implemented.

Operational rule:

```
Disconnect the receiver from DMX equipment before connecting USB charging power.
```

Do not assume that disabling the buck/boost converter provides galvanic isolation from USB ground.

## Low-Battery Detection

Battery state is detected externally rather than using an ESP8266 ADC.

Components:

* LM385Z-1.2 reference
* LM358 comparator
* 10 kΩ trim pot

The LM385 reference is approximately:

```
1.235 V
```

A 10 kΩ resistor supplies the LM385 reference from VBAT.

The trim pot is connected across VBAT and ground. Its wiper provides the battery sense voltage to the LM358.

The trim pot is manually calibrated to the desired low-battery threshold, initially expected to be approximately:

```
3.5 V
```

GPIO behavior:

```
GPIO3 HIGH = battery OK
GPIO3 LOW  = battery LOW
```

Hardware hysteresis is intentionally omitted.

Software should filter the signal instead.

Suggested initial filtering:

```
LOW continuously for ~2 seconds
    -> batteryLow = true

HIGH continuously for ~5 seconds
    -> batteryLow = false
```

These timings should eventually be configurable.

## Wireless Architecture

Use QuickESPNow.

The transmitter broadcasts DMX state to all receivers.

Do not send the realtime DMX stream individually to each receiver.

Do not require per-receiver acknowledgements for realtime DMX data.

Conceptually:

```
               transmitter
                   |
              BROADCAST
              /   |   \
             /    |    \
           RX1   RX2   RX3 ...
```

This prevents communication overhead from scaling directly with receiver count.

## Wireless Refresh Rate

Wireless universe refresh rate and physical DMX refresh rate are separate concepts.

The initial wireless refresh rate should be deliberately conservative:

```
WIRELESS_REFRESH_HZ = 1
```

This value must be configurable.

Testing will gradually increase it until a stable practical rate is established.

QuickESPNow's ESP8266 implementation has limited throughput, so do not assume full DMX refresh rates are practical over the wireless transport.

If PC updates arrive faster than the configured wireless refresh rate, retain only the newest universe.

Example:

```
PC updates:          30 Hz
wireless refresh:    5 Hz
```

The transmitter should send approximately five snapshots of the latest universe per second.

It should NOT queue the other 25 obsolete intermediate states.

## Wireless Packet Design

A complete 512-channel universe will need to be fragmented into multiple ESP-NOW packets.

The exact packet format should be established during the relevant feature implementation after inspecting QuickESPNow's actual payload limits/API.

Each fragment is expected to contain at least:

* protocol version
* packet type
* universe number
* frame/sequence number
* fragment index
* fragment count
* payload length
* channel payload

Use fixed-size data structures.

Avoid dynamic allocation in the realtime data path.

Include compile-time packet-size checks.

## Receiver Buffering

Receivers must never expose a partially received universe to the physical DMX output.

Use double buffering:

```
activeUniverse[512]
stagingUniverse[512]
```

Wireless fragments are written into the staging buffer.

Only after every fragment belonging to the same sequence has arrived may the completed universe replace the active universe.

Example:

```
Wireless frame 100 complete
    -> active = 100

Frame 101 missing fragment
    -> discard 101
    -> continue outputting 100

Frame 102 complete
    -> active = 102
```

This behavior is fundamental to the project.

## Physical DMX

Physical DMX generation is handled by espDMX.

The intended output is normal DMX512:

```
250000 baud
8 data bits
no parity
2 stop bits
valid BREAK
valid Mark After Break
start code 0
up to 512 channel slots
```

Physical DMX output continues independently of wireless updates.

For example:

```
wireless update = 1 Hz
physical DMX output = ~30 Hz
```

The receiver therefore repeatedly transmits its most recently completed universe even when no new wireless data has arrived.

The exact physical refresh behavior follows espDMX's intended API/implementation (interrupt-driven, self-refreshing at 44 Hz+).

## Receiver Startup Safety

The receiver must not output arbitrary UART/boot data onto DMX.

Expected startup sequence:

1. Keep MAX3485 DE disabled.
2. Initialize GPIO.
3. Initialize universe buffers.
4. Initialize QuickESPNow (if needed for this feature).
5. Initialize espDMX (`dmxA.begin()`).
6. Establish a valid initial universe (`dmxA.setChans()`).
7. Start controlled DMX operation.
8. Enable MAX3485 only when safe.

A future configuration option may determine whether the receiver:

* outputs a zero universe immediately after startup, or
* waits for its first valid wireless universe before enabling MAX3485.

## Transmitter

Initial transmitter hardware is simply:

```
PC
 |
USB
 |
USB/serial
 |
ESP8266
 |
QuickESPNow
```

No MAX3485 is required on the transmitter.

The eventual goal is for the transmitter to emulate enough of the ENTTEC DMX USB Pro serial protocol that common PC lighting software can send universe data directly to it.

## ENTTEC Compatibility

The eventual PC-facing interface should emulate the relevant portions of the ENTTEC DMX USB Pro protocol.

This should be developed as its own feature.

Do not mix ENTTEC parsing implementation into unrelated wireless or receiver tasks.

The initial requirement is primarily to accept full-universe DMX updates from existing lighting software.

## Receiver Telemetry

Receivers will eventually send low-rate telemetry back to the transmitter.

Telemetry is separate from the realtime DMX broadcast.

Expected telemetry includes:

* receiver ID
* uptime
* battery-low state
* last completed wireless sequence
* complete universes received
* incomplete/dropped universes
* malformed packets
* time since last valid universe
* RSSI/link information where QuickESPNow exposes it
* firmware version
* protocol version

Telemetry should occur approximately every 3-5 seconds with timing offsets/jitter so all receivers do not transmit simultaneously.

Telemetry must remain lower priority than realtime DMX reception.

## Receiver Identification

Receivers should derive a persistent identifier from the ESP8266 MAC address, chip ID, or another built-in unique value.

A short human-readable representation should also be available, for example:

```
RX-A31F
```

A pairing/configuration system is not currently required.

## Future Management Interface

A future transmitter feature may expose a small status panel showing information such as:

```
Receiver    Battery    Link    Dropped    Last Seen

RX-A31F       OK       Good       0         1.2s
RX-728B       LOW      Good       2         0.8s
RX-19C2       OK       Fair      14         1.7s
```

This is NOT part of the initial implementation.

The telemetry architecture should merely avoid making such an interface difficult to add later.

## Fail-Safe Philosophy

The realtime system favors fresh state over guaranteed delivery.

Do not retransmit obsolete DMX universes merely to guarantee delivery.

Expected behavior:

```
lost wireless fragment
    -> discard incomplete universe

lost wireless universe
    -> retain previous active universe

transmitter temporarily disappears
    -> continue outputting previous universe

newer universe arrives
    -> accept it when complete

PC produces updates faster than RF link
    -> discard obsolete unsent states
```

This is appropriate because an old lighting command generally has less value than the newest available state.

## Coding Guidelines

Prefer:

* fixed-size buffers
* static allocation
* non-blocking state machines
* `millis()` / `micros()` scheduling
* short wireless callbacks
* named constants
* explicit packet structures
* compile-time assertions
* small modules with clear responsibilities
* comments around hardware-specific behavior

Avoid:

* unnecessary dynamic allocation
* `String` in timing-sensitive code
* long blocking delays
* unbounded queues
* unnecessary abstraction
* FreeRTOS
* PlatformIO
* guessed library APIs

Inspect the locally checked-out QuickESPNow and espDMX source whenever their behavior is uncertain.

## Dependency Revisions

Both dependencies are cloned directly from their GitHub repositories into `./libraries/`.

```
QuickESPNow
Repository: https://github.com/gmag11/QuickESPNow
Commit: ec3e337bfdbb744d430b685c8af99298b5b6b91b
Local modifications: None

espDMX
Repository: https://github.com/mtongnz/espDMX
Commit: 02eb697f5b0b2874eafe461d699d699d6204796cdde
Local modifications: None (unmodified, upstream "compile-error" fix commit)
```

These local copies MUST be used for compilation (see Build Information). A different
`QuickESPNow` version (2.4.0) exists in the user Arduino library directory
(`~/Arduino/libraries`); it must not be picked up by the compiler.

### Library API / Compatibility Observations (Feature 1)

QuickESPNow (ESP8266):

* Correct include: `#include <QuickEspNow.h>`.
* Precompiled global instance: `quickEspNow` (no local instance needed).
* Initialization: `quickEspNow.begin(channel, interface, synchronousSend)`.
  `channel` 0-14 selects the channel, `255` follows the current WiFi channel.
  `interface` is `WIFI_IF_STA` (default) or `WIFI_IF_AP`.
* Broadcast: `quickEspNow.sendBcast(payload, len)`;
  unicast: `quickEspNow.send(dstAddress, payload, len)`.
* Receive callback: `onDataRcvd(callback)` with signature
  `void(uint8_t* address, uint8_t* data, uint8_t len, signed int rssi, bool broadcast)`.
* Send-status callback: `onDataSent(callback)` with signature
  `void(uint8_t* address, uint8_t status)`.
* RSSI is available through the receive callback. The library subtracts ~100 dB
  from the raw `wifi_pkt_rx_ctrl_t.rssi` value; the library source comments note
  the result "should be in dBm" but the offset is not fully understood.
  Treat RSSI values as relative until hardware testing.
* Max payload: `ESPNOW_MAX_MESSAGE_LENGTH` = 255 bytes;
  `ESP_NOW_MAX_DATA_LEN` = 250 bytes is the actual transmit limit enforced by
  `send()`. A 512-channel universe will require fragmentation.
* The ESP8266 implementation uses the classic `espnow.h` API,
  `ESP8266WiFi.h`, and `ETSTimer` tasks. It compiles cleanly against
  `esp8266:esp8266` core 3.1.2.
* `DEBUG_LEVEL` is undefined in the local copy, so the debug-logging path
  (and its optional `QuickDebug.h` dependency) is compiled out. No patch needed.

espDMX:

* Correct include: `#include <espDMX.h>` (library name is "espDMX").
* Pre-declared global instances: `dmxA` (UART0/GPIO1), `dmxB` (UART1/GPIO2).
  Instantiate locally to avoid conflicts; we use `dmxA` on UART0.
* `begin()` initializes the library (no parameters needed for default no-LED mode).
* Output is interrupt-driven (UART TX-FIFO-empty ISR); no `update()` call required.
* `setChans(data, numChans, startChan)` (1-based) sets channel data.
* BREAK (~115 µs) / MAB (~7 µs) via GPIO bit-bang, then 250000 baud 8N2.
* Self-refreshes at 44 Hz+; full 512-channel frame at least once per second.
* Trailing-zero channel trimming (min 30, +30 headroom).
* Compiles unmodified against esp8266 core 3.1.2 (verified).
* Hardware-verified 2026-08-21: full 512-channel universes, channels ≥255, BREAK/MAB accepted by fixture; continuous self-refresh on UART0/GPIO1 without library patches.

## Build Information

Receiver target:

```
esp8266:esp8266:generic
```

Libraries are pinned to the local project copies via `--library`, so the
compiler must not resolve them from `~/Arduino/libraries` (which contains a
newer, incompatible `QuickESPNow` 2.4.0).

### Receiver

Verified 2026-08-21 against `esp8266:esp8266` core 3.1.2, arduino-cli 1.4.1.
Re-verified after library replacement (ESP-Dmx → espDMX):

```
arduino-cli compile \
  --fqbn esp8266:esp8266:generic \
  --library ./libraries/QuickESPNow \
  --library ./libraries/espDMX \
  ./receiver
```

Result: success (exit 0). Flash usage 241,696 / 1,048,576 bytes (23%),
RAM 28,932 / 80,192 bytes (36%). Verbose output confirmed both libraries were
compiled from `./libraries/QuickESPNow` (v0.8.1) and `./libraries/espDMX`
(commit 02eb697f...); only the core-provided `ESP8266WiFi` library was taken from the
installed board package.

#### Flashing (receiver)

The ESP-01 is socketed and programmed via esptool after removal from hardware:

```bash
./flash_receiver.sh
```

This script compiles and flashes to `/dev/ttyUSB0`. Adjust the port as needed.

### Transmitter

```
TBD
```

## Development Status

Update this section as features are completed.

### Feature 1: Project Setup / Dependency Verification

Status: COMPLETE (compile-verified 2026-08-21, not hardware-verified)

Completed:

* repository structure established (`./receiver/`, `./libraries/`, `./shared/`, `./transmitter/`)
* QuickESPNow cloned from https://github.com/gmag11/QuickESPNow at
  commit `ec3e337bfdbb744d430b685c8af99298b5b6b91b` (no local modifications)
* espDMX cloned from https://github.com/mtongnz/espDMX at
  commit `02eb697f5b0b2874eafe461d699d699d6204796cdde` (no local modifications)
* both library APIs inspected (see Dependency Revisions)
* minimal receiver sketch created at `./receiver/receiver.ino`
  (defines pin constants, includes both libraries)
* both mandatory libraries verified to coexist in a single build
* successful compile against `esp8266:esp8266:generic` using the local library
  copies pinned via `--library` (see Build Information)
* exact build command documented (see Build Information)

Not done (intentionally out of scope):

* no ESP-NOW transmission or reception implemented
* no pin configuration or callbacks wired up
* no wireless packet structures, fragmentation, or buffering
* no low-battery monitoring or telemetry

### Library replacement: ESP-Dmx → espDMX (basic usage)

Status: COMPLETE (compile-verified + espDMX hardware-verified 2026-08-21 ✓)

Completed:

* espDMX library integrated into `./receiver/receiver.ino` with minimal usage pattern:
  - `dmxA.begin()` initializes the library on UART0/GPIO1.
  - `dmxA.setChans(universe, DMX_UNIVERSE_CHANNELS, 1)` sets channel data;
    output is interrupt-driven and self-refreshing (no `update()` call).
* Channel-cycling test pattern preserved (one channel marked with 0xAA every 0.5s across all 512 channels).
* GPIO pin allocation unchanged (GPIO1 DMX data, GPIO2 DE control, GPIO3 battery low input).
* No patches applied to espDMX — the library compiles and works unmodified against core 3.1.2 on hardware.

Not done (intentionally out of scope):

* no QuickESPNow wireless communication implemented
* no wireless packet structures, fragmentation, or buffering
* no ENTTEC serial input/parser
* no low-battery GPIO monitoring
* no receiver telemetry
* no status/management interface

### espDMX hardware verification

Status: COMPLETE (hardware-verified 2026-08-21)

Verified items:

* full 512-channel universes transmitted continuously
* channels ≥255 included in moving test pattern (channel cycling across all 512 slots)
* channel 512 held at 0x01 to force full-universe transmission
* valid BREAK (~115 µs) / MAB (~7 µs) with 250 k baud 8N2 accepted by DMX fixture
* continuous self-refreshing output without explicit `update()` calls (interrupt-driven, ~44 Hz+)

Library state: espDMX works unmodified (commit 02eb697f...). No patches required.

Note: `libraries/ESP-Dmx/` (Rickgg fork) and `libraries/patches/*.patch` belong to the earlier abandoned approach; they are not used by this receiver build.

### Future Features

Expected approximate sequence:

1. Project setup and dependency verification ✓
2. Patch espDMX library to match hardware requirements (if needed) — *resolved (not required)*
3. Hardware verification of espDMX output (channels ≥255, full 512-channel transmission) — *verified 2026-08-21*
4. Basic QuickESPNow transmitter/receiver communication
5. Wireless packet format and fragmentation
6. Receiver universe reconstruction/double buffering
7. Configurable transmitter wireless refresh
8. ENTTEC serial input/parser
9. Low-battery GPIO monitoring
10. Receiver telemetry
11. Status/management interface
12. Reliability and throughput testing
13. Hardware-specific cleanup and fail-safe refinement

This ordering may change as hardware testing reveals constraints.

## Important Development Rule

Do not treat this README as evidence that a feature already exists.

It describes the intended architecture.

Check the actual source and Development Status before assuming functionality has been implemented.

Likewise:

```
successful compilation != successful hardware validation
```

Hardware-dependent behavior must be tested on real ESP8266/MAX3485/DMX hardware before being considered complete.
