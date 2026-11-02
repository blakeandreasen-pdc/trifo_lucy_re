# Camera and audio

## Reading the cameras from shared memory

The camera node writes hardware-encoded H.264 into small rings in `/dev/shm`, for example `TrifoSemaphore_lucy_camera-image_data_h264`.

- Each ring has a 4 KiB header and 3 slots, starting at `0x1000`.
- Each slot holds `u64 1 | u64 ts_us | u64 len`, then a protobuf whose bytes field carries Annex-B NAL units. SPS and PPS arrive in-band with every keyframe.
- The metadata for slot k sits at `0x8c + 0x20*k` within its slot.

`server/lucy_stream.py` reads the rings through one long-lived `/system/bin/sftp-server` per stream, so there are no process forks on the robot. It orders frames by timestamp and serves them over HTTP. Browsers get fragmented MP4 through `fmp4.py`.

The feeds:

- Main camera: 1920x1080 at about 20 fps.
- ToF "night vision" camera: 224x172 at about 10 fps.

Practical findings:

- Reading both cameras at once tears more frames: about 7% torn, against about 1 in 619 for the main camera alone. The server checks for torn frames and drops them.
- Only read while someone is watching. A constant SSH video tap cost about half a core.
- Chrome plays the stream well. Firefox on Android skipped backwards with the same feed.

## Waking the cameras on the dock

The cameras normally run only while she's active. Sending `STREAM_CONTROL "1"` on rx key 10 wakes them for about 15 s with no manual mode and no brushes. Resending every 2.5 s keeps them awake.

Underneath, this is `cloud_node` signalling `manager_node` on `TrifoIPC_manager_node_REQ`:

- ServiceMsg `08 02 1a 05 12 03 0a 01 <code>`
- `0x10` = CLOUD_START_STREAM
- `0x11` = CLOUD_STOP_STREAM

The 15 s timeout belongs to `cloud_node`. Sent locally, the signal has no timeout, so stop it with `0x11`.

## Native stream with sound

She can push her own RTMP stream with AAC audio, here received by [MediaMTX](https://github.com/bluenviron/mediamtx). It needs two things:

1. The server must answer her owner query with her bound user id, read from `/data/user/app/bind_user_id`. Set `BIND_USER_ID` in `capture_server.py`. The published copy leaves it blank.
2. Her stream hostnames must resolve to your server. See `server/tools/hosts_add_stream.sh`.

The on-robot RTSP server was a dead end: `RTSP_THROB` never opens port 8554.

## Microphone

- The mic is half-duplex. Talking switches it off.
- `RTMP_THROB` plus `STREAM_CONTROL "1"` resent every 2.5 s is enough. No manual mode or brushes are needed, and a clean can carry on at the same time.
- A silent recording of a quiet room isn't necessarily a fault. A 20 s test with a radio playing recorded real sound, while an earlier one in a quiet room was digital silence. The ES8316 noise gate is the likely reason, but that isn't confirmed.

## Speaker

`server/say.py` makes speech with `edge-tts`, converts it to 44.1 kHz stereo with `ffmpeg`, loudness-matches it to her own prompts (about -10 LUFS), copies it to the robot, and plays it with `tinyplay`. The DAC mixer switches are turned on only for the clip.

The intercom uses `START_TALK`, which needs her live stream running. See `server/tools/talk.py`.
