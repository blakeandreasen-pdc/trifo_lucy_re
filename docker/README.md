# Docker: unrooted Lucy with live camera and driving

Runs `capture_server.py` (the local cloud) plus [MediaMTX](https://github.com/bluenviron/mediamtx) for the camera. No root on the robot is needed.

## What works without root

- Everything in the "No" column of the main README.
- **Live camera, 640x480, video only.** Lucy pushes her own RTMP stream, the one the old app watched, when she gets `RTMP_THROB` + `STREAM_CONTROL "1"` (rx key 10) every 2.5 s. On this robot she streamed without any owner (`BIND_USER_ID`) reply. Leave `BIND_USER_ID` blank: a wrong value makes her unbind.
- **Driving** with `MANCTRL` (`S`, then `K` every 3 s, then `ANGLE:N` while held and `ANGLE:0` on release).

The 1080p feed, the map and smooth joystick driving still need root (`lucy_stream.py`).

## Setup

1. DNS: on the resolver Lucy uses, forward two wildcard domains to the docker host:
   - `*.trifo.com`: the local cloud (she uses `euiot` and `eudispatch`)
   - `*.lightfieldcamera.com.cn`: the video push (she uses `pt` and `push`, with `lt` and `live` for pulls)

   Wildcards are simplest and also catch names she might use that aren't listed here. If your DNS can't do wildcards, add those six names as individual records.
2. Copy the config files:
   ```sh
   cd docker
   cp .env.example .env                  # set SERVER_IP, TZ
   cp ../server/config.yaml config.yaml  # set server.ip to the same IP
   ```
   Set `server.ip` explicitly. With `auto`, the server would hand Lucy the container's bridge IP.
3. Run `docker compose up -d --build`.

Lucy reconnects within about 20 s of the server coming up.

## Pages

- `http://<host>/` (or `:8110`): the full control page. Its Camera card plays the live stream and has a Snapshot button.
- `http://<host>/live.html`: the live controller. It has the camera, a hold-to-drive D-pad (with arrows/WASD, Q/E to spin, Space to stop), start/pause/dock/find, and snapshots.
- `http://<host>:8888/lucy`: plain HLS player.

The camera only runs while someone is watching. `mediamtx/lucy-cam.sh` starts when a viewer opens path `lucy`. It sends the wake commands, then relays her `app-name/<id>` stream into `lucy`. MediaMTX stops it about 70 s after the last viewer leaves, and Lucy stops pushing about 15 s later.

## Security

There's no authentication on the web UI, the API or the stream. Keep it on the LAN, and never port-forward or reverse-proxy it publicly.
