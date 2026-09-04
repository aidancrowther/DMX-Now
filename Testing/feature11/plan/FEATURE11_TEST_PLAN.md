# Feature 11 Telemetry Smoke Test

## Purpose

Verify that the integrated transmitter receives telemetry from a receiver and
returns a valid multipart report in response to the binary management command.

## Hardware

* Transmitter ESP8266 connected to the host, normally `/dev/ttyUSB0`.
* At least one powered receiver listening on the same ESP-NOW channel.
* The receiver should have been running long enough to emit its normal
  telemetry packet (approximately every 4–5 seconds).

The test does not send ENTTEC DMX data. It only sends the management request,
so it can be run while the receiver is operating normally.

## Run

From the project root:

```bash
python3 Testing/feature11/tools/test_telemetry.py --port /dev/ttyUSB0
```

The utility opens the transmitter at `115200 8N2`, sends a CRC-16 protected
`GET_RECEIVER_TELEMETRY` request, and waits up to eight seconds for the complete
multipart response.

## Pass criteria

The test passes when:

* At least one management response part is received.
* Every part has a valid `A5 5A` frame and CRC-16/CCITT.
* All parts have the same report sequence and part count.
* Parts are present in order from index zero through `partCount - 1`.
* At least one receiver record is present.
* Receiver link state, battery state, and protocol version are valid.

This is a compile and live-link smoke test, not a complete RF reliability test.