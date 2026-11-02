# Other robot notes

## Security mode

`SET_MONITOR_STATE "1"` / `"0"` on key 15 flips `monitor_mode`. She stays docked and silent, and `perception_node` runs motion detection on the depth camera.

Each event lands in `/data/user/app/monitor/`:

- `<t>.jpg`: a 480x270 still.
- `<t>.gif`: not really a GIF. It's a header followed by about 13 colour JPEGs and about 16 night-vision JPEGs, concatenated.

There's no audio, and no upload attempts were seen. `server/security.py` copies the events, builds real GIFs, and can send text-only alerts through [ntfy](https://ntfy.sh). In the published copy, the "Telegram me" option on the page only writes to the log. Add your own messenger in `_notify`.

`SET_MONITOR_PERSON_ONLY_STATE` is being tested. There's no evidence yet that it's honoured.

## Run log

`server/run_log.py` builds one entry per row of `tb_detail`, her own record of each clean, and adds detail from her logs:

- start and end signals from `manager_node`
- states, relocalisations and map saves from `slam_node`
- named problems and battery level from `sensor_node`

Her `/system/bin/awk` is broken, so use `busybox awk`.

## Mopping

The firmware has mopping support:

- a sensed mop plate (`use_mop_rack`)
- water levels 0-3 (pump duty 7/10/13 of period 100)
- clean mode 2 = mop
- commands `MOPPING_MODE`, `GET_MOPPING_MODE`, `water_pump`

On this robot, fitting the plate and tank changed nothing: `clean_mode` stayed 1 and `mopping_status` stayed empty, docked and during a run. She accepted and confirmed a water level sent mid-run.

The tank seems to be a passive seep tank with no electrical connection, so these settings look like leftovers from firmware shared across Trifo models. That's a conclusion from looking at it, not a proven one. It also stopped her docking on carpet.

## Wi-Fi setup

Setup is by QR code through the camera only. `libtrifo_core_wificfg.so` has no access-point code. The QR text is a standard Wi-Fi QR with extras: `WIFI:T:<type>;P:"<password>";S:<ssid>;U:<user id>;C:<country>;...`

The country picks the cloud domain from a fixed list in her config, so a QR can't point her at your server by itself.

## USB

Her four USB host buses are EHCI/OHCI. The only device-side controller is the dwc3, used by the board's micro-USB for ADB and MTP. So the USB-A port under the lid is a host port, which is why a PC never sees her through it. No script or binary was found that runs updates from a USB stick.

## Her localisation

From her own logs:

- The "large shift" and "too new" bursts every couple of minutes are planned. Between zigzag lanes she holds still, freezes the mapper and re-zeroes the gyro.
- Her map-to-odometry correction jumped 10-35 cm every 5-10 s on an old map. A fresh map cut the median step from about 10 cm to about 5 cm, and big steps from about 1.4 to about 0.4 per minute. The old map had doubled walls, which is the likely cause.
- `server/tools/slam_runs.py` prints a per-run summary of this.

## Things that didn't work

- **On-robot RTSP:** port 8554 never opens.
- **`LUCY_MAP_MGR` REFRESH:** no effect. Promote a map by hand with `server/tools/promote_map100.sh`.
- **Replying to her upload requests:** she keeps asking regardless.
- **`velocity` motion commands:** the MCU ignores them.
- **HLS for live video:** works, but it's too laggy for driving.
- **Decoding the `.ogm` upload file:** a costly dead end and no longer needed.
