# macOS host daemon

The daemon can run on macOS using the platform-selected PTY backend. The
ESP8266 transmitter is connected through a macOS serial device, usually a
`/dev/cu.*` path.

## Install the LaunchAgent

From the `wireless_dmx_daemon` directory, using the Python environment where
the package and `pyserial` are installed:

```bash
python3 macos/install_launch_agent.py \
  --config "$(pwd)/configs/default.conf"
```

The installer creates:

```text
~/Library/LaunchAgents/com.dmxnow.daemon.plist
~/Library/Logs/DMX Now/daemon.log
~/Library/Logs/DMX Now/daemon.error.log
```

Load the generated agent:

```bash
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.dmxnow.daemon.plist"
```

Check or stop it with:

```bash
launchctl print "gui/$(id -u)/com.dmxnow.daemon"
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.dmxnow.daemon.plist"
```

The generated plist uses the Python interpreter that ran the installer, so a
virtual environment can be used without editing the plist manually.

## Management-only LaunchAgent

The LaunchAgent uses the role from the selected TOML configuration. To run the
management interface alongside a standalone physical-DMX retransmitter, use a
configuration containing:

```toml
[daemon]
mode = "management_only"

[transmitter]
device = "/dev/cu.YOUR_TRANSMITTER_ADAPTER"
```

Install it with that configuration:

```bash
python3 macos/install_launch_agent.py \
  --config "$(pwd)/configs/default.conf"
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.dmxnow.daemon.plist"
```

Management-only mode suppresses ordinary DMX input and output from the host
bridge. It retains receiver discovery and telemetry, fail-safe configuration,
receiver output control, locate, channel gates, and explicit priority traffic.
The physical retransmitter remains the only normal-DMX authority. If the
transmitter firmware is locked to management-only, it must be connected to this
host and must not be connected to the retransmitter's physical DMX input.

For an interactive session instead of a background agent:

```bash
wireless-dmx-dashboard --management-only \
  --config "$(pwd)/configs/default.conf"
```

The dashboard starts its own in-process daemon. Do not run this command while a
LaunchAgent for the same transmitter is active.

## PTY and Art-Net inputs

On Linux, the daemon uses `LinuxPtyBackend`; on macOS it uses the matching
`MacOSPtyBackend`. Both provide the same binary PTY interface for ENTTEC and
optional raw-DMX inputs. Art-Net remains available on UDP 6454 and is an
equivalent input path when a lighting application does not accept the generated
macOS PTY path directly.

The initial macOS backend intentionally uses the ordinary POSIX PTY path
reported by `pty.openpty()` rather than installing a hardware-style virtual
serial driver.