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
configuration, output control, locate, and explicit priority/gate operations.

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
./helpers/flash_transmitter.sh \
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

Compile the validated recovery image without flashing:

```bash
cd "/home/aidancrowther/Documents/Projects/Cline Testing" && \
./helpers/flash_retransmitter.sh \
  --define=-DRETRANSMITTER_DIAGNOSTICS=1 \
  --define=-DRETRANSMITTER_DIAGNOSTIC_BROADCAST=1
```

The helper is compile-only unless `-f` is provided. Flashing requires the
retransmitter's isolated programmer port and must be performed by the operator:

```bash
cd "/home/aidancrowther/Documents/Projects/Cline Testing" && \
./helpers/flash_retransmitter.sh \
  --define=-DRETRANSMITTER_DIAGNOSTICS=1 \
  --define=-DRETRANSMITTER_DIAGNOSTIC_BROADCAST=1 \
  -f \
  --port <RETRANSMITTER_PROGRAMMER_PORT>
```

The diagnostic build's broadcasts are useful for lab diagnosis but add an
extra ESP-NOW packet approximately once per second. For production deployment,
build a normal image with diagnostics disabled:

```bash
cd "/home/aidancrowther/Documents/Projects/Cline Testing" && \
./helpers/flash_retransmitter.sh \
  --define=-DRETRANSMITTER_DIAGNOSTICS=0 \
  --define=-DRETRANSMITTER_DIAGNOSTIC_BROADCAST=0
```

Always record the SHA-256 printed or calculated for the image that is flashed.
Never use a test-only scheduling or fault-injection define in a deployment
image.

### Receiver

For normal operation, build and flash the production receiver:

```bash
cd "/home/aidancrowther/Documents/Projects/Cline Testing" && \
./helpers/flash_receiver.sh \
  -f \
  --port <RECEIVER_PROGRAMMER_PORT>
```

The silent diagnostic receiver is a test image only. It disables physical DMX
output and should not be left installed on a receiver connected to fixtures:

```bash
./helpers/flash_receiver.sh \
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
   cd wireless_dmx_daemon
   wireless-dmx run --management-only --config configs/config.example.toml
   ```

6. Verify telemetry receiver identities and link state.
7. Verify normal DMX still comes exclusively from the physical retransmitter.

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