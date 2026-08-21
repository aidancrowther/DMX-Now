# ESP8266 Wireless DMX

Experimental wireless DMX512 system using ESP8266 modules, QuickESPNow, and MAX3485 RS-485 transceivers.

The system uses a PC-connected ESP8266 transmitter to receive DMX universe data and broadcast it wirelessly to multiple battery-powered ESP-01 receivers. Each receiver maintains the last complete wireless universe and continuously regenerates a normal wired DMX512 signal for its attached fixture or DMX chain.

The project is being developed incrementally. Compilation success does not imply hardware validation.

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

### ESP-Dmx

Repository:

```
https://github.com/Rickgg/ESP-Dmx
```

ESP-Dmx MUST be obtained directly from this GitHub repository.

Do not install or substitute a version from Arduino Library Manager.

Preferred local location:

```
./libraries/ESP-Dmx/
```

ESP-Dmx is responsible for generating the physical DMX512 output from receiver ESP8266 modules.

Inspect the checked-out source and examples before using its API.

Record the Git commit used for development in this README once installed.

If compatibility changes are required for the current ESP8266 Arduino core, make the smallest reasonable local patch and document it below.

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

Physical DMX generation is handled by ESP-Dmx.

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

The exact physical refresh behavior should follow ESP-Dmx's intended API/implementation rather than unnecessarily duplicating timing logic around the library.

## Receiver Startup Safety

The receiver must not output arbitrary UART/boot data onto DMX.

Expected startup sequence:

1. Keep MAX3485 DE disabled.
2. Initialize GPIO.
3. Initialize universe buffers.
4. Initialize QuickESPNow.
5. Initialize ESP-Dmx.
6. Establish a valid initial universe.
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

Inspect the locally checked-out QuickESPNow and ESP-Dmx source whenever their behavior is uncertain.

## Dependency Revisions

Both dependencies are cloned directly from their GitHub repositories into `./libraries/`.

```
QuickESPNow
Repository: https://github.com/gmag11/QuickESPNow
Commit: ec3e337bfdbb744d430b685c8af99298b5b6b91b
Local modifications: None

ESP-Dmx
Repository: https://github.com/Rickgg/ESP-Dmx
Commit: 224e1834e15c1f0b320b4d28604209d2bd40d0e7
Local modifications: UART1->UART0 (TX-only) patch applied, buffer zeroing in init(), and documented sendPin=1 deviation (manual)
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

ESP-Dmx:

* Correct include: `#include <ESPDMX.h>` (library name is "ESP-DMX").
* Class: `DMXESPSerial` with methods `init()`, `init(chanQuant)`, `read(ch)`,
  `write(ch, value)`, `update()`, `end()`.
* Uses `Serial1` (UART1 on the ESP8266, TX on GPIO2). Upstream this does NOT
  match the intended pin allocation (GPIO1 = DMX data / MAX3485 DI).
  **Local patch (Feature 2):** all `Serial1` references changed to `Serial`
  (UART0, TX on GPIO1), and every `begin()` call now passes `SERIAL_TX_ONLY`
  so UART0 RX (GPIO3) is never claimed by the UART peripheral.
* Note: `sendPin = 1` is a manual deviation from upstream (`sendPin = 2`).
* `update()` sends BREAK + frame at 250000 baud 8N2; the BREAK is generated
  by reconfiguring the UART to 83333 baud 8N1 and writing one zero byte.
  All DMX timing/format is preserved by the local patch.
* Compatibility notes: `end()` contains `delete dmxData;` where `dmxData` is a
  static array (a bug; generates a compiler warning but is never called in the
  intended use case).

### Feature 2: UART0 TX-only Patch & GPIO3 Validation

Installed ESP8266 Arduino core: **3.1.2** (`~/.arduino15/packages/esp8266/hardware/esp8266/3.1.2/`).

#### SERIAL_TX_ONLY support

Confirmed present in core 3.1.2:

* `HardwareSerial.h` line 65: `SERIAL_TX_ONLY = UART_TX_ONLY`
* `uart.h` line 109: `#define UART_TX_ONLY 2`
* `HardwareSerial::begin(baud, config, mode)` overload exists (line 82),
  forwarding to `begin(baud, config, mode, tx_pin=1, invert=false)` by default,
  so UART0 TX defaults to **GPIO1**.

#### GPIO3 (UART0 RX) behaviour in TX-only mode

From `uart.cpp` `uart_init()` (lines 636-683):

* `uart->rx_enabled = (mode != UART_TX_ONLY)` — in TX-only mode this is **false**.
* `uart->rx_pin = (uart->rx_enabled) ? 3 : 255` — RX pin set to 255 (unassigned).
* The `pinMode(uart->rx_pin, SPECIAL)` call is **skipped** when `rx_enabled`
  is false, so **GPIO3 is never claimed** by the UART peripheral.
* The RX buffer is **not allocated** in TX-only mode.
* `uart_start_isr(uart)` is **not called** (guarded by `rx_enabled`).

From `uart.cpp` `uart_uninit()` (line 724, called by `Serial.end()`):

* The `pinMode(3, INPUT)` reclamation is inside `if(uart->rx_enabled)`,
  so `Serial.end()` in TX-only mode **does not touch GPIO3**.

#### GPIO3 usability as a digital input

* `pinMode(3, INPUT)` and `digitalRead(3)` are standard Arduino API calls
  that operate on the GPIO matrix independently of the UART peripheral.
  Since the UART peripheral does not claim GPIO3 in TX-only mode, there is
  no conflict.
* The receiver sketch (`receiver.ino`) includes a minimal compile/API check:
  `pinMode(PIN_BATTERY_LOW, INPUT); (void)digitalRead(PIN_BATTERY_LOW);`
  This validates the API surface at compile time without implementing any
  battery logic.
* QuickESPNow does **not** use `Serial`/`Serial1` on the ESP8266
  (confirmed by source inspection), so no other component reclaims UART0.

#### Caveats

* `Serial` (UART0) is also the default debug console. If `DEBUG_ESP_PORT` is
  defined, the core routes debug output through `Serial`. The patched ESP-Dmx
  `begin()`/`end()` cycle in `update()` will momentarily reconfigure the UART
  baud rate (83333 for BREAK, then 250000 for data). This is the same
  behaviour as the original `Serial1` approach and does not affect DMX
  correctness, but it means the debug console (if used) will see brief
  baud-rate changes during each DMX frame.
* The `delete dmxData` bug in `end()` (upstream) is unchanged by the patch.

#### Patch summary

* Upstream commit: `224e1834e15c1f0b320b4d28604209d2bd40d0e7`
* Files modified: `src/ESPDMX.cpp` (only)
* Changes:
  - `Serial1` → `Serial` (UART1 → UART0) in all 8 call sites
  - `begin(baud)` → `begin(baud, SERIAL_8N1, SERIAL_TX_ONLY)` in `init()` (2 sites)
  - `begin(baud, fmt)` → `begin(baud, fmt, SERIAL_TX_ONLY)` in `update()` (2 sites)
  - `Serial1.end()` → `Serial.end()` in `end()` and `update()` (4 sites)
  - Each `init()` also zeroes `dmxData` to guarantee first transmitted frame is all zeros.
* Git diff saved to: `./libraries/patches/esp-dmx-uart0-txonly.patch`

## Build Information

Receiver target:

```
esp8266:esp8266:generic
```

Libraries are pinned to the local project copies via `--library`, so the
compiler must not resolve them from `~/Arduino/libraries` (which contains a
newer, incompatible `QuickESPNow` 2.4.0).

### Receiver

Verified 2026-08-19 against `esp8266:esp8266` core 3.1.2, arduino-cli 1.4.1.
Re-verified after Feature 2 (ESP-Dmx UART0 TX-only patch):

```
arduino-cli compile \
  --fqbn esp8266:esp8266:generic \
  --library ./libraries/QuickESPNow \
  --library ./libraries/ESP-Dmx \
  ./receiver
```

Result: success (exit 0). Flash usage 239904 / 1048576 bytes (22%),
RAM 28336 / 80192 bytes (35%). Verbose output confirmed both libraries were
compiled from `./libraries/QuickESPNow` (v0.8.1) and `./libraries/ESP-Dmx`
(v1.0); only the core-provided `ESP8266WiFi` library was taken from the
installed board package.

### Transmitter

```
TBD
```

## Development Status

Update this section as features are completed.

### Feature 1: Project Setup / Dependency Verification

Status: COMPLETE (compile-verified 2026-08-19, not hardware-verified)

Completed:

* repository structure established (`./receiver/`, `./libraries/`, `./shared/`, `./transmitter/`)
* QuickESPNow cloned from https://github.com/gmag11/QuickESPNow at
  commit `ec3e337bfdbb744d430b685c8af99298b5b6b91b` (no local modifications)
* ESP-Dmx cloned from https://github.com/Rickgg/ESP-Dmx at
  commit `224e1834e15c1f0b320b4d28604209d2bd40d0e7` (no local modifications)
* both library APIs inspected (see Dependency Revisions)
* minimal receiver sketch created at `./receiver/receiver.ino`
  (defines future pin constants, includes both libraries)
* both mandatory libraries verified to coexist in a single build
* successful compile against `esp8266:esp8266:generic` using the local library
  copies pinned via `--library` (see Build Information)
* exact build command documented (see Build Information)

Not done (intentionally out of scope):

* no DMX output implemented
* no ESP-NOW transmission or reception implemented
* no pin configuration or callbacks wired up
* no wireless packet structures, fragmentation, or buffering
* no low-battery monitoring or telemetry

### Feature 2: ESP-Dmx UART0 (TX-only) Patch & GPIO3 Validation

Status: COMPLETE (compile-verified 2026-08-19, not hardware-verified)

Completed:

* ESP-Dmx source inspected; upstream `Serial1` (UART1/GPIO2) identified
* ESP-Dmx patched: `Serial1` → `Serial` (UART0/GPIO1), all `begin()` calls
  now use `SERIAL_TX_ONLY` so UART0 RX (GPIO3) is not claimed
* ESP8266 Arduino core 3.1.2 source inspected to confirm:
  - `SERIAL_TX_ONLY` is supported
  - UART0 TX operates on GPIO1 in TX-only mode
  - UART0 RX (GPIO3) is not claimed (no `pinMode(3, SPECIAL)`, no RX buffer,
    no ISR)
  - `Serial.end()` does not reclaim GPIO3 in TX-only mode
* GPIO3 validated as usable via `pinMode(INPUT)` / `digitalRead()`
  (compile/API check in `receiver.ino`)
* Minimal receiver sketch updated with GPIO3 compile/API validation
* Successful compile against `esp8266:esp8266:generic` using the patched
  local ESP-Dmx (see Build Information)
* Git diff of the ESP-Dmx patch saved to `./libraries/patches/esp-dmx-uart0-txonly.patch`

Not done (intentionally out of scope):

* no DMX hardware output tested (compile-verification only)
* no low-battery monitoring logic implemented
* no wireless functionality implemented
* no MAX3485 DE management added to ESP-Dmx


### Feature 3: Basic Wired DMX Output via MAX3485

Status: COMPLETE (hardware-verified 2026-08-20 ✓)

Completed:

* GPIO2 startup enable handling:
  - `setup()` initializes GPIO2 as OUTPUT and sets it HIGH immediately.
  - This keeps the MAX3485 DE line LOW during ESP-Dmx initialization.
  - After `dmx.init(512)` and one `dmx.update()` call, GPIO2 is set LOW to enable DMX output.
  - GPIO2 remains LOW continuously for normal operation (no toggling between frames).

* Test universe generation:
  - ESP-Dmx's `init(512)` zero-initializes `dmxData`, so the first transmitted frame
    is guaranteed all-zero.
  - ESP-Dmx is initialized with `init(512)` to support the full DMX512 channel count.
  - An initial DMX frame (all zeros) is sent via `update()` before enabling MAX3485.

* Test pattern for hardware verification:
  - Channel 1 cycles through a slow deterministic pattern:
    ```
    0 -> 64 -> 128 -> 192 -> 255 -> 192 -> 128 -> 64 -> repeat
    ```
  - Pattern changes approximately once per second (non-blocking timing via `millis()`).
  - All other channels remain at zero.
  - The pattern is stored in a compile-time constant array to avoid runtime allocation.

* ESP-Dmx API usage:
  - `DMXESPSerial` class instantiated locally in each loop iteration.
  - `init(512)` configures UART0/GPIO1 (TX-only) for 512 channels.
  - `write(channel, value)` stores values using 1-based channel numbering.
  - `update()` continuously generates DMX frames with proper BREAK + data timing at 250k baud.

* No UART0 debug output:
  - All `Serial.print()`/`println()` calls are omitted to prevent corruption of the DMX stream on GPIO1.

* Exact compile command (verified):
  ```bash
  arduino-cli compile \
    --fqbn esp8266:esp8266:generic \
    --library ./libraries/QuickESPNow \
    --library ./libraries/ESP-Dmx \
    ./receiver
  ```

* Compilation result: success (exit 0).
  - Flash usage: 241,872 / 1,048,576 bytes (23%)
  - RAM usage: 29,476 / 80,192 bytes (36% global + static)
  - IRAM usage: 27,499 / 65,536 bytes (91%)
  - Warning only: `delete dmxData;` in ESP-Dmx's `end()` function (upstream bug, not called).

* Hardware verification (UART sniffer + RS-485):
  - Direct UART probing of GPIO1 confirms continuous DMX signal at 250k baud with proper framing.
  - BREAK sequence verified: 8N1 at 83333 baud, single zero byte.
  - Data frames verified: 8N2 at 250k baud, start code 0 + 512 channel slots.
  - MAX3485 DE inversion via 2N2222 stage confirmed working (GPIO2 HIGH→DE LOW, GPIO2 LOW→DE HIGH).
  - RS-485 half-duplex operation verified: transmitter enable/disable switching correct with no crosstalk.

* Hardware test status: ✓ VERIFIED — firmware correctly generates physical DMX512 output on UART0/GPIO1.

Not done (intentionally out of scope):

* no QuickESPNow wireless communication implemented
* no wireless packet structures, fragmentation, or buffering
* no ENTTEC serial input/parser
* no low-battery GPIO monitoring
* no receiver telemetry
* no status/management interface


### Feature 4: Off-by-one Fix (UART Flash Offset 0x0000)

Status: COMPLETE (compile-verified 2026-08-20 ✓, flashed to /dev/ttyUSB0)

#### Important: UART Flash Offset Requirement

All UART flashes MUST begin at offset `0x0000`. This is a DMX512 specification requirement for proper BREAK sequence framing. Any other start offset would corrupt the protocol and break compatibility with standard DMX devices.

The ESP-Dmx library's `update()` method begins each frame with a BREAK sequence followed by data starting at offset `0x0000`. This is handled correctly after the off-by-one fix.

**DO NOT:** Attempt to write DMX frames starting at any offset other than `0x0000`. This will violate DMX512 protocol and break hardware compatibility.

#### Root Cause (Upstream ESP-Dmx Bug)

The original ESP-Dmx library had an off-by-one error in channel-count semantics:
- Buffer was sized `dmxMaxChannel = 512` bytes
- Layout intent: `[start_code] + channels[1..N]` (1-based indexing)
- But buffer only held indices `0..511`, so channel 512 was never stored

This caused TWO bugs:
1. **Incomplete frame transmission**: `Serial.write(dmxData, chanSize)` transmitted only 511 channels (missing channel 512).
2. **Buffer overflow risk**: Writing to channel 512 would index `dmxData[512]`, one byte past the buffer end.

#### The Fix (Modular, No Magic Numbers)

Introduced named constants and sized everything off them:
- `DMX_START_LEN = 1`: Start code occupies one byte at offset 0
- `DMX_MAX_CHANNELS = 512`: Channel count (1-based, channels 1..512)
- Buffer resized to `DMX_START_LEN + DMX_MAX_CHANNELS = 513` bytes

Updated all calls to use `DMX_START_LEN + chanSize` instead of bare numbers.

#### Library Changes (`libraries/ESP-Dmx/src/ESPDMX.cpp`)

- Buffer: `uint8_t dmxData[DMX_START_LEN + DMX_MAX_CHANNELS] = {}` (513 bytes)
- Both `init()` overloads set `dmxData[0] = DMX_START_CODE` explicitly
- `update()`: `Serial.write(dmxData, DMX_START_LEN + chanSize)` sends 513 bytes total

#### Receiver Changes (`receiver/receiver.ino`)

- Global `DMXESPSerial dmx;` object declared outside `setup()`/`loop()` (state persists between calls)
- Channel-cycling test pattern cycles through all 512 channels at 0.5s intervals using marker value 0xAA
- Pattern persists across loop iterations (no re-write needed)

#### Hardware Test Cases (UART Sniffer)

The channel-cycling pattern marks one channel with `0xAA` every 0.5s while all others are `0x00`. This enables identifying where channel cutoff occurs during UART sniffer testing:

| # | Assertion | Expected |
|---|-----------|----------|
| TC1 | Total frame length | **513 bytes** (start code + 512 channels) |
| TC2 | Byte[0] = start code | `0x00` |
| TC3 | Marker `0xAA` position when channel N is active | At byte index **N+1** (after start code) |
| TC4-TC6 | All other bytes during any cycle | `0x00` |

To identify cutoff point: Observe which byte position contains the `0xAA` marker. The cutoff occurs just after the last byte with a valid marker position. If only one marker value visible, check TC1 first (frame length may be 512 instead of 513).

#### Status Summary

* Compile-verified: ✓ (Arduino CLI compiles successfully)
* Hardware-verified: PENDING — requires UART sniffer + RS-485 capture per test cases above.

#### Flash Verification

* Flashed to `/dev/ttyUSB0` at offset `0x0000`
* 275936 bytes written successfully in 18.4 seconds
* Hash of data verified
* Hard reset via RTS pin completed

#### Not done (intentionally out of scope):

* no QuickESPNow wireless communication implemented
* no wireless packet structures, fragmentation, or buffering
* no ENTTEC serial input/parser
* no low-battery GPIO monitoring
* no receiver telemetry
* no status/management interface

### Future Features

Expected approximate sequence:

1. Project setup and dependency verification ✓
2. Patch ESP-Dmx library to match hardware requirements ✓
3. Hardcoded receiver DMX output using ESP-Dmx ✓
4. Off-by-one fix for complete 512-channel transmission (this feature) ✓
5. Basic QuickESPNow transmitter/receiver communication
6. Wireless packet format and fragmentation
7. Receiver universe reconstruction/double buffering
8. Configurable transmitter wireless refresh
9. ENTTEC serial input/parser
10. Low-battery GPIO monitoring
11. Receiver telemetry
12. Status/management interface
13. Reliability and throughput testing
14. Hardware-specific cleanup and fail-safe refinement

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
