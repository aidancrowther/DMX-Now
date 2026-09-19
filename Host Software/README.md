# Host software

The host-side software is under
[`wireless_dmx_daemon/`](wireless_dmx_daemon/). It is a Python package providing
the DMX bridge, management service, virtual serial backends, Art-Net input,
telemetry, priority control, and terminal dashboard.

Start from the repository root with:

```bash
cd "Host Software/wireless_dmx_daemon"
python3 -m pip install .
wireless-dmx-dashboard --config configs/default.conf
```

See the package README and `../Docs/daemon.md` for Linux/macOS operation,
systemd, LaunchAgent, configuration, and dashboard details.