# Changelog

Newest first. Technical detail is in [docs/](docs/README.md).

## November 2026: the big catch-up

Nothing was pushed here between 23 March and this update, so all of the work below arrived at once. The dates are when the work was done, not when it was committed.

### Stage 7: 3D scanning experiment (31 October)

Feasibility only. Nothing here is a finished feature.

- Measured the ToF camera: 224x172, 5-7 Hz, and about 2 mm frame-to-frame noise at 0.3-0.6 m.
- Colour lines up with depth using the factory calibration file already on the robot.
- Hand-carrying works. Depth keeps running when she's lifted, and the orientation feed stays usable off the floor.
- Found the local signal that wakes the cameras, so a recording can run with the server switched off.
- First rough mesh from 204 depth frames of a folded card box.

See [docs/3d_scanner.md](docs/3d_scanner.md).

### Stage 6: map melding and mopping (29 October)

- `map_merge.py` reads and rebuilds her Cartographer maps. The round trip is byte-identical.
- A rebuilt two-trajectory map loaded on the robot, and she relocalised on it in about 20 s.
- Merging a real new room is **not finished**. Automatic fitting isn't reliable on a small, cluttered overlap, so the planned next step is a manual fit page.
- Map guard now keeps the throwaway maps she would otherwise delete.
- Mopping: the firmware has settings for it, and she accepts and confirms them, but fitting the tank changed nothing in her status. The tank looks passive.
- Driving mode gained a Camera / Night / Off switch.

### Stage 5: rooting helper (27 October)

- `tools/root_lucy.py` automates the timing-critical steps of the [rooting guide](Getting_root_on_lucy.md). It hasn't yet been used on a second robot.

### Stage 4: everyday use (25-26 October)

- Control page redesigned, mobile first, with status, battery, suction and the next scheduled run in the header.
- Cameras work on the dock without manual mode, and Listen no longer needs manual mode either.
- Say box: neural text-to-speech played on her own speaker.
- Run log built from her own logs and database.
- Schedules can target zones or rooms, with their own suction, and can switch security mode.
- Security mode: she sits silent on the dock and saves stills on motion. The server turns them into GIFs and can send text-only alerts.
- Map protection: map guard restores her map if a run saves a much smaller one, and it fired correctly on a real run. Map slots gained previews.
- Polygon keep-out zones and clean zones.

### Stage 3: driving (22-24 October)

- Direct motion commands over her internal ZeroMQ sockets, with a live joystick on the page.
- Parking view: her map plus depth-camera obstacles, placed using the live pose feed.
- Cameras are now only read while someone is watching. The old video tap cost about half a core around the clock.

### Stage 2: zones and rooms (22 October)

- Keep-out and clean zones drawn on the page and sent live, with no restart.
- Zone-only and room-only cleaning.

### Stage 1: eyes, ears and voice (13-17 October)

- Moved the server to an always-on machine.
- **Camera solved:** live H.264 from her shared memory, shown in a browser.
- **Live map solved:** read from shared memory over SSH. Decoding the `.ogm` upload file turned out not to be needed.
- Spot clean to any point on the map.
- Native RTMP stream with sound, once the owner bind reply was found.
- Intercom and half-duplex microphone.
- Named map slots to save, load and switch maps.
- App command table recovered from the decompiled APK. Suction confirmed to run across the full 0-100 range by ear.

### Windows package (April)

- Portable server with `install.bat` and [SETUP.md](server/SETUP.md) for people who haven't rooted their robot.

### Late March research

- Command architecture, shared-memory and ZeroMQ research, now published in [docs/research/](docs/research/README.md).

## March 2026: first public release

Root method, MQTT and dispatch protocols, local control server and web UI, Wi-Fi QR setup, and the collaborative research framework in `collab/`.
