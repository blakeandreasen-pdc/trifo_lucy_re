# Trifo Max

The Trifo Max talks the same cloud protocol as the Lucy, so the local server works with it
unchanged: dispatch, MQTT, registration and the rx command channel are identical. These notes
cover where the Max differs. Everything here was found **without root**, through the cloud
protocol and the Trifo Home 2.6.3 app, on one Max running firmware 3.40.0. Other firmware may
differ.

The Max is product id `1003268244`. In the app, that is product class `y2.f` with feature
class `x2.f` (the Lucy is `x2.c`).

## Differences at a glance

| | Lucy | Max |
|---|---|---|
| Reverse in manual mode | `MANCTRL "ANGLE:8"` | `MANCTRL "ANGLE:10"` |
| Status request | `ALL_INFO_JSON` (key 11) | `ALL_INFO` (key 11). It answers twice: the semicolon `ALL_INFO` and then a full `ALL_INFO_JSON`. Asking for `ALL_INFO_JSON` directly returns empty data |
| Suction | smart-speaker `blowerMode:N` | `blowerMode` is ignored. The app's `BLOWER N` (rx key 2) works, but the robot applies and reports it 1-3 min later |
| Voice prompts | | `VOICE "0"` / `"1"` on rx key 2 turns them off / on; key 3 reads the setting back. The smart-speaker `mute` toggle has no visible effect |
| Voice languages (app lists) | 0-5: Chinese, English (US), English (UK), Spanish, German, French | 0 Chinese, 1 English (US) only |
| Map | live map over SSH (root) | `GET_MAP` on rx key 8, no root needed (below) |
| Map/pose on key 18 | `GET_LUCY_MAP` etc. | no reply |
| Go to point | `A2B` (key 12) | `A2B_NO_CLEAN "x,y"` (key 12) works, in the map's frame (below) |
| Talk and live audio | yes | no: the app disables both for the Max, and testing agrees (below) |
| Depth camera stream (`<id>_cg`) | yes | no; one 640x480 H.264 camera only |
| On-robot RTSP (port 8554) | `RTSP_THROB` never opens it | opens, with credentials from `RTMP_PARAM` (below) |

The Max is slow to answer rx commands. Replies often arrive 50-120 s after the request, so
wait at least two minutes before deciding a command got no reply. A status request within
about 2 s of the robot's login is ignored; asking again 8 s after login works.

## Status codes

Seen on the Max (`clean_state`, first field of `ALL_INFO`):

| Code | Meaning |
|---|---|
| 1 | cleaning |
| 5 | returning to the dock |
| 10 | on the dock after a run |
| 12, 14 | on the dock, charging or full |
| 20 | on the dock with only the camera running |

## Map without root

`GET_MAP` with empty data on rx key 8 is answered with base64 of an **uncompressed** grid.
It starts with the same `ogm` magic as the Lucy's upload file, which may help with decoding
that one.

| Offset | Type | Field |
|---|---|---|
| 0 | 4 bytes | `"ogm\0"` |
| 4 | u32 | 0 |
| 8 | u32 | width (cells) |
| 12 | u32 | height (cells) |
| 16 | f64 | cell size in metres (0.1) |
| 24 | width × height bytes | cells, row by row |
| after cells | f64 little-endian | 6 values: dock x, y, theta, then robot x, y, theta. With only 3 values, they're the robot pose |

- **Cells** are occupancy 0-10. 5 is unknown, below 5 is free, above 5 is an obstacle. The
  app's palette (`h3.z`) paints 5 as `#EFEFEF` and the rest as a teal gradient.
- **Poses** are in metres and radians, in a frame centred on the grid, with x pointing up the
  rows and y to the left along the columns. The app's decoder places them at:
  ```text
  row = round((height * cell / 2 - x) / cell - 0.5)
  col = round((width  * cell / 2 - y) / cell - 0.5)
  ```
  On a fresh map the dock is at the origin.
- **Size varies** from map to map (120×120, 56×56, 40×40 and 24×24 seen).
- **Timing**: docked, the reply comes within seconds. While cleaning, the Max only builds a
  new map every 1-2 minutes (median about 50 s, at most about 120 s), so polling faster just
  returns the same map. The official app polled every 5 s. There are no unsolicited pose
  updates; while cleaning the Max only pushes `ALL_INFO` about every 10 s.
- `GET_MAP` also makes the robot ask to upload a file (0x0303 requests of type 2, and type 0
  with `{"size":1048576}`).

## Go to a point

`A2B_NO_CLEAN` on rx key 12 with data `"x,y"` (metres) drives the Max to that point without
cleaning, and it replies `OK` about a minute later. The point is in the same frame as the
map's poses: `"0.5,0.0"` from the dock drove it 0.5 m straight out and stopped. `A2B` with
cleaning wasn't tested.

## No talk, no microphone

The app decides per model whether to show the intercom and the live-view audio button. For
the Max, `x2.f.q()` (talk) and `x2.f.v()` (live audio) both return `false`, overriding the
parent class. The Lucy's `x2.c` returns `true` for both.

Testing agrees. `START_TALK` (rx key 14) is accepted, and the Max pulls the RTMP stream and
answers `0,<id>` (success), but plays nothing. This was tried with AAC at 8, 16 and 44.1 kHz,
stereo, MP3, in manual mode, and with voice prompts on and off. Its RTMP push is H.264 only,
with no audio track.

For reference, the app's own talk stream is AAC-LC 44.1 kHz mono 128 kbit/s to
`rtmp://<stream host>/app-name/<phone uuid>`. `START_TALK` answers `1` when someone else is
already talking, and the app refuses to talk in states 1, 2, 3, 5, 6 and 7 or during
do-not-disturb. `VOICETALK_PARAM` (key 10) answers slowly with
`pt.lightfieldcamera.com.cn;<key>;app-name;1`.

## On-robot RTSP

Unlike the Lucy, the Max opens an RTSP server on port 8554 after `RTSP_THROB` (rx key 10).
The credentials come from `RTMP_PARAM` (key 10). The Max answered it when it was sent the way
the app sends it: `GET_SYSTEM_CONFIG` (key 15), then `NET_INFO` (key 1), then `RTMP_PARAM`.
Whether the order matters wasn't tested.

- The reply is base64 of AES-128-ECB with PKCS7 padding. The key is the first 16 characters
  of the lowercase hex MD5 of a constant in the app (`h3.s`), used as ASCII:
  ```python
  import base64, hashlib
  from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
  from cryptography.hazmat.primitives.padding import PKCS7

  CONST = bytes([83, 23, 78, 83, 109, 14, 87, 51, 87, 35, 81, 75, 98, 54, 98, 54])
  KEY = hashlib.md5(CONST).hexdigest()[:16].encode()

  def decrypt_rtmp_param(data: str) -> list[str]:
      d = Cipher(algorithms.AES(KEY), modes.ECB()).decryptor()
      raw = d.update(base64.b64decode(data)) + d.finalize()
      u = PKCS7(128).unpadder()
      return (u.update(raw) + u.finalize()).decode().split(";")
  ```
- Decrypted, it's `host;key;port;type;user;pass;path`: port `8554`, user `txen`, a
  12-character password, and the stream's uuid as the path.
- Keep sending `RTSP_THROB` about every 2.5 s, or the server closes again, then open
  `rtsp://txen:<pass>@<robot ip>:8554/<path>` over TCP, e.g.
  `ffprobe -rtsp_transport tcp "rtsp://txen:<pass>@<robot ip>:8554/<path>"`.

It isn't worth using. The SDP advertises H.264 plus AAC 44.1 kHz mono, but the audio track is
empty and malformed, and video alone arrives at about 1 frame per second. The RTMP push is
better.

## Voice language

`LANGUAGE N` on rx key 2 (key 3 reads it) is an index into the app's per-model list in
`res/values/arrays.xml`:

- `voice_language_lists_max`: 0 Chinese (Simplified), 1 English (US)
- `voice_language_lists` (other models): 0-5 Chinese, English (US), English (UK), Spanish,
  German, French
- `voice_language_lists_all` adds 6 Chinese (Traditional), 7 Italian and 8 Japanese, for
  models that download voice packs

The Max answers `OK` to any value from 0 to 8, but only has its built-in voice.
`GET_SYSTEM_CONFIG` lists a single voice, `English(US)`, with
`support_voice_package_download` 0.

## System config

`GET_SYSTEM_CONFIG` (key 15) answers with the robot's feature flags. On the Max:

- supported: do-not-disturb, `power_off`, `optimize_battery_charging`,
  `max_blower_schedule_clean`, `cliff_sensitivity_level` 2
- not supported: mopping, rooms, areas, carpet
- `enable_security` 1, `monitor` 0 with a `monitor_task` schedule of 00:00-23:59

`FIRMWARE_VERSION` answers with the firmware version.

## No reply on the Max

These got no answer within 8 minutes: `CLEAN_INFO`, `CLEAN_TASKS_STATE`, `GET_TASK`,
`GET_CUSTOM_CLEAN_PLAN`, `GET_CUSTOM_CLEAN_PARAM`, `GET_DONOT_DISTURB_MODE`,
`GET_MONITOR_DETAIL`, `LOG_RECORD_LIST` and `GET_TEST_BOT`. The app never sends
`SET_MONITOR_STATE`, and `CHARGER_BASE_CTRL` is only used for the Viva.
