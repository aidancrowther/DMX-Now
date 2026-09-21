# Physical DMX retransmitter deployment

This guide describes deploying the standalone physical-DMX retransmitter with
one or more Wireless DMX receivers. It covers both supported operating modes:

1. **Standalone mode:** the retransmitter is the only normal-DMX authority and
   no management transmitter is required.
2. **Monitored mode:** a separate management-only transmitter provides receiver
   telemetry and control while the physical retransmitter continues to own
   normal DMX.

The production retransmitter target is 10 Hz. It supports complete and partial
physical DMX universes from the DMXUART callback threshold (currently 24 slots)
through 512 slots, zero-filling the unused tail through channel 512. The native
integrated transmitter target is 20 Hz and can be deployed with the host daemon
or as a native transmitter installation without the daemon.

## System roles

```text
DMX lighting source
        |
        v
  RS-485 transmitter
        |
        v
Standalone retransmitter  -- ESP-NOW normal DMX -->  ESP8266 receiver(s)
 UART0/GPIO3 RX                                      GPIO1/UART DMX output

Optional management-only transmitter  -- telemetry/control --> receiver(s)
```

The management-only transmitter is optional. It never replaces the physical
retransmitter as the normal-DMX source. It is used for telemetry, fail-safe
configuration, output control, locate, explicit priority/gate operations, and an
optional read-only observed-universe display. The display is best-effort and does
not affect normal retransmission if the management transmitter or host is offline.

## Hardware wiring

### Retransmitter input

The retransmitter firmware owns ESP8266 UART0/GPIO3 for physical DMX input.
Connect a receive-only RS-485 transceiver:

```text
DMX source RS-485 A/B -> retransmitter RS-485 receiver A/B
RS-485 receiver RO    -> ESP8266 GPIO3 / UART0 RX
RS-485 driver DE/RE   -> disabled
```

The retransmitter must not drive the physical DMX line. Verify A/B polarity,
signal reference, termination, and transceiver voltage levels before powering
the system.

### Retransmitter receiver control and battery comparator

The installed retransmitter uses GPIO2 for remote receiver-input control and GPIO1
for the battery comparator:

```text
ESP8266 GPIO2 -> 2N2222 base/resistor -> MAX3485 receiver /RE
MAX3485 /RE   -> VCC through 10 kOhm; 2N2222 collector pulls /RE to GND
ESP8266 GPIO1 -> battery-level comparator output
```

This polarity means GPIO2 `LOW` leaves the transistor off and enables the DMX
receiver; GPIO2 `HIGH` pulls `/RE` low and disables it. The production helper
leaves this control disabled by default. Use the explicit `--receiver-control`
option to enable the GPIO2 path; `--no-receiver-control` can be used to make the
disabled choice explicit.

Battery monitoring is optional and disabled by default for compatibility. Enable
it with `--battery-monitor` or through `--menuconfig`; the default comparator
polarity treats LOW as battery-low. Use `--battery-low-active-high` when the
comparator output polarity is reversed. Disabled monitoring reports battery
`UNKNOWN` in retransmitter telemetry.

The retransmitter DMXUART instance passes `tx_pin = -1` and `rx_pin = GPIO3`.
On ESP8266 this selects `SERIAL_RX_ONLY`, so UART0 TX/GPIO1 is not claimed by
serial output and can safely be used by the comparator. Do not add serial logging
or change the DMXUART TX pin while the comparator is connected.

GPIO2 is reserved for receiver `/RE` control and is not used for retransmitter
locate indication. Retransmitter locate requests remain available through the
management interface, but have no separate local LED output on this hardware.

### Receiver output

Each receiver uses its own MAX3485 output:

```text
ESP8266 GPIO1 / UART TX -> MAX3485 DI
ESP8266 GPIO2           -> inverted MAX3485 DE control
MAX3485 A/B             -> DMX fixture line
```

See [`hardware.md`](hardware.md) for receiver power, isolation, and GPIO safety
details. The receiver design is not galvanically isolated; observe the stated
power and fixture precautions.

### Optional management transmitter

The management transmitter is a separate ESP8266 connected to the host through
its own USB adapter. Build it as a locked management-only image:

```bash
cd "/home/aidancrowther/Documents/Projects/Cline Testing" && \
./Helpers/flash_transmitter.sh \
  --lock-management-only \
  -f \
  --port <MANAGEMENT_PROGRAMMER_PORT>
```

Do not connect its UART to the retransmitter's physical DMX input. Its role is
ESP-NOW telemetry/control only.

## Radio and universe configuration

All ESP-NOW devices must use the same:

```text
ESP-NOW channel
universe ID
```

The production defaults are defined in the shared `WirelessDMX` protocol and
the retransmitter helper. If a custom channel or universe is used, rebuild the
retransmitter, receiver, and management transmitter consistently.

The physical retransmitter's normal ESP-NOW source MAC must be used when source
filtering is enabled. Do not infer that MAC from a USB programmer; the
retransmitter may be electrically isolated from the host.

## Firmware images

### Retransmitter

Build the normal production image without flashing:

```bash
cd "/home/aidancrowther/Documents/Projects/Cline Testing" && \
./Helpers/flash_retransmitter.sh
```

The helper is compile-only unless `-f` is provided. Flashing requires the
retransmitter's isolated programmer port and must be performed by the operator:

```bash
cd "/home/aidancrowther/Documents/Projects/Cline Testing" && \
./Helpers/flash_retransmitter.sh -f \
  --port <RETRANSMITTER_PROGRAMMER_PORT>
```

With no extra options, the helper builds the production 10 Hz image with
diagnostics and diagnostic broadcasts disabled. Do not add diagnostic defines
to a production image. Diagnostic builds are lab-only and add an extra
ESP-NOW packet approximately once per second; if one is required for a specific
bench investigation, enable it explicitly with `--define` and restore the
normal image afterward.

For a custom non-default build, the helper also provides an interactive
configuration menu. It prompts for the ESP-NOW channel, universe ID, wireless
rate, TX drain timeout, and TX overhead. Press Enter at each prompt to accept
the production defaults:

```bash
cd "/home/aidancrowther/Documents/Projects/Cline Testing" && \
./Helpers/flash_retransmitter.sh --menuconfig
```

The menu defaults are channel `1`, universe `1`, rate `10` Hz, TX drain timeout
`100` ms, TX overhead `27` ms, receiver `/RE` control enabled on GPIO2, and
battery monitoring disabled. `--menuconfig` can be combined with `-f`
and `--port <RETRANSMITTER_PROGRAMMER_PORT>` when the resulting custom image
is ready to flash.

Always record the SHA-256 printed or calculated for the image that is flashed.
Never use a test-only scheduling or fault-injection define in a deployment
image.

### Receiver

For normal operation, build and flash the production receiver:

```bash
cd "/home/aidancrowther/Documents/Projects/Cline Testing" && \
./Helpers/flash_receiver.sh \
  -f \
  --port <RECEIVER_PROGRAMMER_PORT>
```

The silent diagnostic receiver is a test image only. It disables physical DMX
output and should not be left installed on a receiver connected to fixtures:

```bash
./Helpers/flash_receiver.sh \
  --silent-capture \
  --diagnostic-baud 115200 \
  -f \
  --port <RECEIVER_PROGRAMMER_PORT>
```

Restore the production image after testing.

## Standalone deployment: no management transmitter

Use this mode when normal DMX must continue even if the host or management
transmitter is absent.

1. Flash the production receiver image(s).
2. Flash the production retransmitter image.
3. Connect the DMX source to the retransmitter's receive-only RS-485 input.
4. Power the retransmitter and receivers.
5. Confirm receiver output on a DMX fixture or monitor.
6. Feed normal DMX from the lighting controller.

No `/dev/ttyUSB0` management device, host daemon, or management transmitter is
required for normal retransmission. The physical retransmitter owns the normal
DMX authority and broadcasts the latest complete physical-DMX universe.

## Monitored deployment: management-only transmitter present

Use this mode when telemetry, receiver discovery, fail-safe configuration, or
remote output control is required.

1. Flash production receiver images.
2. Flash the production retransmitter image.
3. Flash the management transmitter with `--lock-management-only`.
4. Configure the daemon's transmitter device for the management transmitter.
5. Run the daemon in management-only mode if no host DMX bridge is desired:

   ```bash
   cd "Host Software/wireless_dmx_daemon"
   wireless-dmx run --management-only --config configs/config.example.toml
   ```

6. Verify telemetry receiver identities and link state.
7. Verify normal DMX still comes exclusively from the physical retransmitter.

In monitored mode, the dashboard's manual-universe view should report the latest
complete retransmitter observation as `LIVE`. It is normal for it to be briefly
`STALE` or `UNAVAILABLE` during startup, radio loss, or management-transmitter
reconnect. This display is not a substitute for receiver-side DMX validation.

When using channel gates, entering `LOCKED` captures the value currently shown by
the observer. Later physical-DMX observations cannot alter that channel, while
explicit management priority edits can. This permits a locked channel to retain
the live value at the moment the operator establishes the lock.

The management transmitter may send telemetry/control and explicit priority
traffic, but it must not be configured as a competing ordinary-DMX source.

## Host daemon configuration

The host serial connection uses:

```text
115200 baud
8 data bits
no parity
2 stop bits
```

The management-only transmitter is normally the host serial device. Do not
assume Linux USB enumeration order is stable; identify the adapter by hardware
identity or operator-confirmed wiring.

The normal daemon bridge mode is for a deployment where the host owns normal
DMX. Do not run bridge mode with a physical retransmitter also connected to the
same normal-DMX universe unless intentional source arbitration has been
designed and verified.

## Operational checks

Before enabling fixtures:

- confirm all receivers use the production image;
- confirm the retransmitter input transceiver is receive-only;
- confirm receiver output transceivers are wired to the intended DMX lines;
- confirm channel, universe ID, and source authority;
- confirm no test diagnostic or fault-injection flags remain enabled;
- confirm receiver fail-safe mode and timeout;
- confirm the last complete universe is held during a temporary wireless loss;
- confirm a fresh valid universe recovers output;
- verify that a 512-slot source reaches channels 237–512;
- record firmware hashes and wiring/USB identities.

## Recovery and troubleshooting

### No output

Check, in order:

1. DMX source is transmitting and RS-485 polarity is correct.
2. Retransmitter input transceiver is powered and receive-only.
3. ESP-NOW channel and universe ID match.
4. Receiver is running production firmware and its MAX3485 is enabled.
5. Receiver fail-safe has not disabled the line.
6. The retransmitter has accepted complete input frames.

### 512-slot tail is zero

Do not accept the deployment. Verify that the retransmitter is using the
DMXUART BREAK-handling fix and that the source generates all 512 channels. The
expected symptom of the historical defect was a first mismatch at channel 237.

### Management telemetry is absent

Normal retransmission does not require the management transmitter. For
telemetry, verify that the management image is locked management-only, the host
daemon uses 115200 8N2, and all devices share the configured radio channel.

### Test image recovery

Replace diagnostic receiver or retransmitter images with production builds
before returning hardware to fixtures. Keep the diagnostic reports and flashed
image hashes with the deployment record.

## Production targets

The production targets are:

```text
Native/integrated transmitter: 20 Hz
Standalone physical retransmitter: 10 Hz
```

The native/integrated transmitter may be used with the Linux host daemon for
Art-Net, ENTTEC, PTY, telemetry, and management workflows, or used as a native
transmitter installation without the daemon when the application supplies the
transmitter's supported input path directly. The standalone retransmitter is
the 10 Hz physical-DMX-to-ESP-NOW deployment described in this guide.