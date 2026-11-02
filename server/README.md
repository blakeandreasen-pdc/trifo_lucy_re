# Lucy server

Two parts run side by side on a PC on the same network as the robot.

| Program | Port | Needs root? | What it does |
|---------|------|-------------|--------------|
| `capture_server.py` | 8080 | No | Stands in for Trifo's cloud: commands, status, schedules, basic web UI |
| `lucy_stream.py` | 8090 | Yes | The full control page: camera, map, zones, driving, runs, security |

## Basic server, no root needed

The Windows walkthrough is in [SETUP.md](SETUP.md), and `install.bat` does most of it.

1. Install PyYAML: `pip install pyyaml`.
2. Generate TLS certificates in this folder. Lucy doesn't verify them.
   ```bash
   openssl req -x509 -newkey rsa:2048 -keyout mqtt_key.pem -out mqtt_cert.pem \
     -days 3650 -nodes -subj "/CN=euiot.trifo.com"
   ```
3. Point `euiot.trifo.com` and `eudispatch.trifo.com` at your server. See the [main README](../README.md).
4. Run `python capture_server.py` and open `http://<server>:8080`.

## Full control page, rooted robot

These steps are written from one working setup and haven't been tried from scratch on a second machine, so expect to adjust things.

1. [Root your Lucy](../Getting_root_on_lucy.md) and set up SSH with a key.
2. Edit `config.yaml`: set `lucy.ip` and `lucy.ssh_key`.
3. Replace the placeholders. Search the folder for `YOUR_SERVER_IP` and `YOUR_LUCY_IP`. `BIND_USER_ID` in `capture_server.py` is blank in this copy, so set it to the contents of `/data/user/app/bind_user_id` on your robot if you want her native stream.
4. Build the on-robot helpers (below) and copy them to `/data/lucy_local/` on the robot. Don't use `/data/local/tmp`, because `run.sh` wipes it.
5. Install the Python packages: `pip install pyyaml numpy pillow edge-tts`. Some tools also need `scipy`.
6. Optional: [MediaMTX](https://github.com/bluenviron/mediamtx) for her native stream with sound, and `ffmpeg` for the Say box. `say.py` calls `ffmpeg` through WSL, so change that if you're not on Windows with WSL.
7. Run `python capture_server.py` and `python lucy_stream.py`, then open `http://<server>:8090/view`. Driving mode is at `/view?drive`.

To run her DNS redirect on the robot rather than the router, bind-mount your own hosts file over `/etc/hosts` from a line near the top of `/data/user/app/run.sh`, and keep a copy of the original `run.sh`.

### On-robot helpers

Built on Linux or WSL as static aarch64 binaries, for example:

```bash
aarch64-linux-gnu-gcc -static -O2 -o zq zq.c
```

| File | Purpose |
|------|---------|
| `onrobot/zq.c` | ZeroMQ client for her internal sockets (driving, pose feed) |
| `onrobot/depthscan.c` | Obstacle points from the depth camera for the parking view |
| `onrobot/depthdump.c` | Depth and RGB capture for the 3D scanner |
| `onrobot/usock.c` | Raw unix socket probe |
| `onrobot/scanrec.sh` | Standalone 3D scan recording |
| `onrobot/watch_inputs.sh` | Read-only log of button presses |

## Files

| File | Purpose |
|------|---------|
| `capture_server.py` | Dispatch, MQTT, REST API, scheduler |
| `lucy_stream.py` | Video, control page and its API |
| `view.html`, `runs.html`, `runs.js`, `park_view.js` | The control page |
| `map_reader.py`, `map_preview.py`, `map_merge.py`, `map_guard.py` | Maps: live, previews, merging, protection |
| `pose_feed.py`, `align.py`, `drive_link.py`, `drive_proto.py` | Position, parking view, driving |
| `security.py`, `run_log.py`, `say.py`, `fmp4.py` | Security mode, run log, speech, browser video |
| `lucy_live.py`, `lucy_proto.py` | SSH and protobuf helpers |
| `lucy_control.py`, `send_command.py` | Command line control |
| `lucy_protos_full.proto` | Protobuf definitions recovered from the firmware |
| `app_command_table.md` | Command table from the old app |
| `tools/` | Working scripts and one-off probes from the research, in varying states of polish |

Useful ones in `tools/`: `lucy_sh.py` (run a script on the robot), `map_slots.sh`, `slam_runs.py`, `talk.py`, `root_lucy.py`.

## Ports

| Port | Protocol | Purpose |
|------|----------|---------|
| 7990 | TLS | QLCloud dispatch (Lucy connects here first) |
| 17766 | TLS/MQTT | MQTT broker (commands and status) |
| 443 | HTTPS | Voice packages, OTA |
| 8080 | HTTP | Basic REST API and web UI |
| 8090 | HTTP | Control page and video |
| 9999 | TCP | Local control socket (CLI tool) |

## Safety

- The control page has no login. Only run it on a network you trust, and don't expose it to the internet. It can show her camera and play sound in your home.
- Back up `/data/user/app/run.sh` and your map before changing anything on the robot.
- Read the clock warning in [docs/driving.md](../docs/driving.md) before sending your own motion commands.
