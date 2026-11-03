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
- `http://<host>/live.html`: full-screen driving. The camera fills the screen with a thumb joystick over it, which snaps to the nearest of her 8 moves. You can also drive with WASD/arrows or a game controller's left stick. It has Stop/Dock/Find/Clean and snapshots, and goes in and out of manual mode on its own.
- `http://<host>:8888/lucy`: plain HLS player.

The camera only runs while someone is watching. `mediamtx/lucy-cam.sh` starts when a viewer opens path `lucy`. It sends the wake commands, then relays her `app-name/<id>` stream into `lucy`. MediaMTX stops it about 70 s after the last viewer leaves, and Lucy stops pushing about 15 s later.

## Behind a reverse proxy

The pages look for the camera endpoint at `/lucy/whep` on their own address first. If it isn't there, they fall back to `http://<host>:8889`. That fallback can't work behind an HTTPS proxy, because the browser blocks it as mixed content and the port usually isn't proxied. So route `/lucy/whep` to MediaMTX alongside the UI. For nginx:

```nginx
location / {
    proxy_pass http://<host>:8110;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

# WebRTC signalling (WHEP) for the camera. This covers /lucy/whep and /lucy/whep/<session>.
location /lucy/whep {
    proxy_pass http://<host>:8889;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_buffering off;
}
```

Put the same `allow`/`deny` rules on both locations.

Only the signalling goes through the proxy. The video goes straight from the browser to `<SERVER_IP>:8189/udp` (`SERVER_IP` in `.env`), so viewers need a route to that address: the LAN, or a VPN into it.

## Security

There's no authentication on the web UI, the API or the stream. Keep it on the LAN, and never port-forward or reverse-proxy it publicly.
