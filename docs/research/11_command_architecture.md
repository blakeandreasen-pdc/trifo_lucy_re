# Lucy Command Architecture — Complete Reference

## Live Session Results (2026-03-26)

### 1. Smart Speaker Command — Exhaustive Test (FINAL)

We tested every plausible keyword via strace on cloud_node. This is the **complete and final** list of recognized smart speaker commands:

| Command | Effect |
|---------|--------|
| `start` | Starts cleaning (triggers CLOUD_REQUEST_MAP_MANAGE_ON, mode switch signals) |
| `stop` | Stops cleaning (cloud request mode: 3) |
| `dock` | Return to dock (cloud request mode: 4) |
| `locate` | Find me / beep (cloudserver.cc:3199 "recv find me message") |
| `mute` | Toggle mute (accepted silently) |
| `setVolume:N` | Set volume level |
| `volumeRelative:N` | Relative volume change |
| `blowerMode:N` | Set suction level |

**All other keywords tested and REJECTED** ("Unknown smart speaker command"):
`home`, `resume`, `MANBLOWER`, `charge`, `recharge`, `pause`, `cancel`, `clean`, `edge`, `unmute`, `find`, `find_me`, `findme`, `spot`, `zigzag`, `monitor`, `camera`, `patrol`, `quiet`, `silent`, `loud`, `max`, `low`, `high`, `turbo`

**Conclusion**: There are exactly 8 smart speaker commands. No hidden keywords exist.

### 2. QLRPDataItem Is Cloud-Only

Sending QLRPDataItem JSON as DP 2 value results in "Unknown smart speaker command." The QLRPDataItem format was a **cloud-server protocol** — the Trifo cloud server translated app commands into device-level smart speaker keywords. The device itself never saw QLRPDataItem directly. This rules out Phase B's hypothesis from below.

### 3. Only DP 1 and DP 2 Have Handlers

- **DP 1** → "app bind success" (iot_interface.c:137)
- **DP 2** → smart speaker handler (iot_interface.c:147 → cloudserver.cc:3165)
- **DP 3, 4, 5, 8, 9** → silently ignored, no log output

This means all the DP key-value commands listed in Layer 2C below were handled by the **cloud server**, not by cloud_node on the device. The on-device MQTT path is limited to the 8 smart speaker commands.

### 4. ZMQ Protobuf Captured

Strace with `sendto()` traced on cloud_node revealed the ZMQ IPC protocol details:

- ZMQ uses `sendto()` on Unix domain sockets, not `write()`
- **FD→socket mapping**: FD 130→`cloud_stream_status_data`, FD 136/137→`manual_controller_info` REQ/REP, FD 234/235→`cloud_node` REQ/REP
- Captured ServiceMsg protobuf with `MapperControlInfoItemMsg` containing `./lucy_map/pose_graph_map.pbstream`
- **Map polling every ~10s**: LOAD_MAP → QUERY_MAP → reply with size:169466, map_update_time

This confirms the ZMQ path is the correct way forward for advanced control (Phase C).

### 5. RTSP Status

Toggled `enable_rtsp` to `true` in `config_cloud_node.json`, restarted cloud_node. Log shows `"enable rtsp status: 1"` (was 0). But **port 8554 never opens** — the Live555 RTSP server may need additional dependencies or an active camera stream to bind the port.

### 6. UDP Discovery

cloud_node broadcasts `trifo-robot_AA:BB:CC:DD:EE:FF` on **UDP port 18888**. This is the local network discovery mechanism used by the Trifo app to find robots on the LAN.

### 7. Status Reporting Unreliable

Lucy's MQTT status updates (updps) are frequently stale. Robot reported "cleaning" long after docking. Added warnings to code and docs. Any automation relying on status must account for this staleness.

---

## Overview

Lucy has **three layers of control**, each with different capabilities and access requirements. Understanding these layers is critical for knowing what's possible and what's needed to achieve it.

```
Layer 3: Smart Speaker (MQTT)     ← What we have now
Layer 2: App Commands (MQTT)      ← Partially understood
Layer 1: Internal IPC (ZMQ)       ← Full control, runs on Lucy
Layer 0: MCU Serial (UART)        ← Raw hardware, AES-128-CTR encrypted
```

---

## Layer 3: Smart Speaker Commands (WORKING)

**Access**: Via MQTT downdps, DP ID 2, lowercase strings.
**Path**: capture_server → MQTT → cloud_node → smart speaker handler → guidance_node

| Command | Parameters | Status | Description |
|---------|-----------|--------|-------------|
| `start` | — | Confirmed | Begin auto-clean run |
| `stop` | — | Confirmed | Stop in place |
| `dock` | — | Confirmed | Return to charging dock |
| `locate` | — | Confirmed | Trigger find-me beep/voice |
| `mute` | — | Recognized | Toggle mute |
| `pause` | — | Maps to `stop` | Pause cleaning |
| `setVolume:N` | N = 0-100 | Untested | Set volume |
| `volumeRelative:N` | N = +/-delta | Untested | Adjust volume |
| `blowerMode:N` | N = mode int | Confirmed | Set suction level |

**Blower modes** (from config):
- Default: 28, Default pet: 23
- Min blower: 25, Max blower: 78, Max pet: 88
- Range tested: 21-24 and 33

**MQTT payload format**:
```json
{
  "data": [{"i": 2, "v": "start"}],
  "subid": "LUCXXXXXXXXXXXXX0",
  "expire": 1711400000
}
```

**Limitations**: No spatial awareness. Can't specify where to clean, which room, manual driving, wall-follow mode, etc.

---

## Layer 2: App Commands (PARTIALLY UNDERSTOOD)

### 2A. Status Queries (UPPERCASE, DP 2)

These work via MQTT but only return data — they don't control the robot.

| Command | Description |
|---------|-------------|
| `GET_WORK_STATUS` | Full status (battery, position, cleaning state, etc.) |
| `BATTERY` | Battery percentage |
| `CLEAN_STATE` | Current cleaning state |
| `CLEAN_AREA` | Area cleaned (m²) |
| `CLEAN_TIME` | Time spent cleaning |
| `GET_SYSTEM_CONFIG` | Robot configuration |
| `GET_LUCY_POSE` | Robot position (x, y, theta) in map frame |
| `GET_LUCY_MAP` / `GET_MAP` | Map data |
| `GET_MOPPING_MODE` | Mopping config |
| `GET_DONOT_DISTURB_MODE` | DND settings |
| `GET_MONITOR_STATE` | Camera/surveillance status |
| `GET_CUSTOM_CLEAN_PARAM` | Custom cleaning parameters |

### 2B. App-Path Action Commands (FORMAT UNKNOWN)

These commands exist in the APK and cloud_node but we haven't successfully sent them yet. They likely use a different encoding — either a different DP ID, or the `QLRPDataItem` JSON wrapper.

**QLRPDataItem format** (from APK decompilation):
```json
{
  "head": "rp",
  "cmd": "<COMMAND_NAME>",
  "key": "2",
  "data": "<command_payload>",
  "sum": "0",
  "index": "0",
  "requestid": "<uuid>"
}
```

This JSON object is likely sent as the `v` value of a DP, wrapped in the standard downdps envelope:
```json
{"data": [{"i": 2, "v": "{\"head\":\"rp\",\"cmd\":\"SET_WALL_FOLLOW_ENABLE\",\"data\":\"1\"}"}]}
```

**Known action commands** (untested):

| Command | Likely Payload | Purpose |
|---------|---------------|---------|
| `SET_WALL_FOLLOW_ENABLE` | `"1"` or `"0"` | Enable/disable wall-follow (edging) mode |
| `SET_CUSTOM_CLEAN_PARAM` | JSON params | Set cleaning parameters |
| `LUCY_MAP_MGR` | Protobuf (Base64?) | Map/zone management |
| `SET_MAP_MANAGE_STATE` | State enum | Map management mode |
| `SET_MONITOR_STATE` | `"1"` or `"0"` | Enable surveillance camera |

### 2C. DP Key-Value Commands (UNTESTED)

The QLCloud downdps handler processes individual data points. Beyond DP 2 (smart speaker), there are other DPs for specific functions. From the APK: DP IDs 1, 2, 3, 4, 5, 8, 9, 10, 11, 14, 15, 16, 18, 22 exist.

**Known DP keys** (from cloud_protocol.md §5.5, sent cloud → robot):

| DP Key | Type | Description |
|--------|------|-------------|
| `running_mode_with_dock` | enum | Start cleaning + return to dock |
| `running_mode_without_dock` | enum | Start cleaning, no dock return |
| `resume` | bool | Resume paused cleaning |
| `suspend` | bool | Pause cleaning |
| `wait_restart_clean` | bool | Restart after waiting |
| `countdown` | int | Scheduled clean countdown |
| `wheel_speed` | float | Manual drive speed (max 8.0) |
| `charger_pose` | binary | Set charger position |
| `donot_disturb_state` | bool | DND mode |
| `voice_volume` | int | Volume |
| `voice_type` | int | Voice pack |
| `water_pump` | int | Mopping intensity |
| `enable_security` | bool | Surveillance mode |
| `room_id` | int | Target room |
| `room_name` | string | Room name |
| `room_type` | enum | Room type |
| `upload_map` | bool | Trigger map upload |

**Unknown**: Which DP ID maps to which key. This mapping is inside cloud_node's downdps handler and needs reverse engineering.

---

## Layer 1: Internal ZMQ IPC (FULL CONTROL)

This is where the real power is. All robot behavior is controlled through ZeroMQ protobuf messages on UNIX domain sockets in `/data/local/tmp/`.

**Access**: Requires running code ON Lucy (we have root SSH).

### Command Flow

```
cloud_node receives MQTT
    ↓ translates to protobuf
CloudStatusDataItemMsg on cloud/cloud_status_data (PUB/SUB)
    ↓
guidance_node receives and executes
    ↓
guidance_node sends MCU commands via sensor_node
    ↓
sensor_node → TBot::SetMove() → MCU serial → motors
```

### Key RPC Endpoints

| Endpoint | Client → Server | Purpose |
|----------|----------------|---------|
| `manual_controller_info` | cloud_node → guidance_node | **Manual driving** (joystick) |
| `motion_command` | cloud_node → guidance_node | **Direct wheel velocities** |
| `mapper_control_info` | cloud_node → guidance_node | **Map control** (save/load/reset) |
| `cloud_planning_params` | cloud_node → guidance_node | **Planning parameters** (zones, rooms) |
| `robot_control` | manager_node → sensor_node | **Mode control** (start/stop) |
| `robot_utility_command` | cloud_node → sensor_node | **Hardware** (LEDs, voice, blower) |

### Protobuf Message Types (ServiceMsg oneof)

```protobuf
message ServiceMsg {
  oneof data {
    ManualControlInfoItemMsg     manual_control_info      = 5;  // Manual control data
    ManualControllerInfoItemMsg  manual_controller_info   = 6;  // Manual drive commands
    MapperControlInfoItemMsg     mapper_control_info      = 7;  // Map/zone control
    MotionCommandItemMsg         motion_command           = 8;  // Wheel velocities
    CloudStatusDataItemMsg       cloud_status             = 2;  // Cloud → robot commands
    RobotUtilityCommandItemMsg   robot_utility_command    = 13; // LED/voice/blower
    SystemModeMsg                system_mode              = 14; // Mode switches
    // ... others for sensor data, calibration, etc.
  }
}
```

### What's possible via ZMQ

| Capability | Message Type | Notes |
|-----------|-------------|-------|
| Manual forward/back/turn | ManualControllerInfoItemMsg | Joystick-style driving |
| Direct wheel speed | MotionCommandItemMsg | Left/right wheel velocities |
| Wall-follow mode | CloudStatusDataItemMsg | Changes cleaning mode to wall-follow |
| Zone cleaning | MapperControlInfoItemMsg | Send zone polygons |
| Room cleaning | CloudStatusDataItemMsg | Select room by ID |
| Save/load map | MapperControlInfoItemMsg | Map management |
| LED control | RobotUtilityCommandItemMsg | Ring light colors |
| Voice playback | RobotUtilityCommandItemMsg | Audio commands |
| Motor speed | RobotUtilityCommandItemMsg | Individual brush/blower duty cycles |

---

## Layer 0: MCU Serial Commands (RAW HARDWARE)

The STM32F407 MCU accepts commands over `/dev/ttyS3` (AES-128-CTR encrypted, CRC-16 framed).

**TBot API** (from libtrifo_robot.so):

| Method | Description |
|--------|-------------|
| `SetMove(dir, speed, angular_vel, distance, flags)` | Move robot in direction |
| `SetStop(flags)` | Emergency stop |
| `SetDock(flags)` | Initiate/cancel docking |
| `SetWallFollow(dir, speed, flags)` | Wall-following mode |
| `SetCleanMotor(motor_id, duty_cycle)` | Individual motor control (-127 to +127) |
| `SetCarpetBoostControl(enable)` | Carpet boost mode |
| `SetLight(LightData)` | LED ring control |
| `SetIMUHeating(enable)` | IMU heater |

**MoveDirection enum**: Forward, Backward, Left, Right, RotateCW, RotateCCW (exact values unconfirmed)

**Motor IDs**:
- Main brush: dock=20%, clean=50% duty cycle
- Side brush: dock=30%, clean=40% (dock low power=15%)
- Blower: min=25, max=78, max_pet=88

**Blocked by**: AES-128-CTR key/IV unknown. Key likely derives from device serial or firmware binary.

---

## Zone Cleaning Architecture

The user's intuition was correct: **zones are an app-side concept, not an internal robot feature**. The architecture is:

1. Robot builds occupancy grid map (SHM, live data)
2. Robot saves map as OGM (archive, end of run)
3. Map is sent to app (via MQTT or cloud upload)
4. **App displays map, user draws zones/rooms/virtual walls on it**
5. App converts drawn shapes to grid coordinates (polygon vertices)
6. App packages coordinates as protobuf and sends via MQTT
7. cloud_node receives and translates to `MapperControlInfoItemMsg`
8. guidance_node receives zone definitions and plans paths within zones

**Zone types** (from APK enum):
- `DESIGNATED_AREA` — "clean this rectangle/polygon"
- `NO_GO_ZONE` — "don't enter this area"
- `VIRTUAL_WALL` — "treat this line as a wall"
- `ROOM_SEGMENTATION` — "these are the room boundaries"
- `ROOM_SEGMENTATION_MODIFY` — "update room boundaries"

**To implement our own zones**, we need:
1. Live map display (SHM data — ready now)
2. Draw zones in web UI (browser-side)
3. Convert pixel coordinates → grid coordinates
4. Package as MapperControlInfoItemMsg protobuf
5. Send via ZMQ to guidance_node (on-robot script) or via MQTT (if we crack the format)

---

## Wall Follow / Edging

**What the app does**: Sends `SET_WALL_FOLLOW_ENABLE` command via MQTT.

**What happens internally**:
1. cloud_node receives → publishes CloudStatusDataItemMsg with wall-follow flag
2. guidance_node switches planning mode to wall-follow
3. guidance_node sends `SetWallFollow(direction, speed, flags)` to MCU via sensor_node
4. MCU executes wall-hugging path (follows wall/obstacle on one side)

**Config flags**:
- `visable_wall_follow_switch: true` — wall follow UI toggle visible in app
- `visable_tirvs_switch: true` — TIRVS (camera-based obstacle avoidance) toggle

**Edging quality**: The effectiveness depends on the speed, direction, and sensor thresholds. The MCU's wall-follow uses IR side sensors to maintain distance. If edging was poor with the app, the parameters might need tuning — something we could potentially do via `SET_CUSTOM_CLEAN_PARAM` or direct ZMQ.

---

## Recommended Implementation Path

### Phase A: Live Map Display (READY NOW)
- Read SHM over SSH → display occupancy grid in web UI
- Read `frame_pose.csv` or `GET_LUCY_POSE` → show robot position
- Existing commands (start/stop/dock) for basic control
- No new RE needed

### Phase B: DP Key-Value Commands (NEEDS TESTING)
Try sending the QLRPDataItem format for app commands:
```python
# Hypothesis: app commands are JSON-wrapped in DP 2's value
cmd = json.dumps({"head":"rp", "cmd":"SET_WALL_FOLLOW_ENABLE", "data":"1", "key":"2", "requestid": str(uuid4())})
send_downdps_command(dp_id=2, value_str=cmd)
```
Also try other DP IDs (3, 4, 8, etc.) with simple values to map DP ID → function.

### Phase C: On-Robot ZMQ Agent (MOST POWERFUL)
Write a Python script that runs on Lucy and:
1. Connects to ZMQ IPC sockets directly
2. Sends protobuf commands to guidance_node
3. Provides a simple TCP API that our capture_server can call via SSH tunnel

This bypasses ALL MQTT/cloud complexity and gives us full control including:
- Manual driving (joystick)
- Zone cleaning (polygon coordinates)
- Wall-follow with custom parameters
- Direct motor control
- Real-time pose and map data

**Challenge**: Reverse engineering the exact protobuf field numbers and enum values for:
- CloudStatusDataItemMsg
- ManualControllerInfoItemMsg
- MapperControlInfoItemMsg
- MotionCommandItemMsg

**Approach**: The `.proto` definitions might be extractable from the binaries (protobuf descriptors are sometimes compiled in), or we can use Ghidra to read how cloud_node populates these messages.

### Phase D: MCU Direct Control (OPTIONAL)
Crack the AES-128-CTR key for the serial link and send raw MCU commands. This gives hardware-level control but is the hardest path and probably not needed if ZMQ works.

---

## Experiments To Run (Next Live Session)

### Quick wins (via MQTT, no Lucy access needed beyond capture server):
1. **Test QLRPDataItem format**: Send `{"head":"rp","cmd":"SET_WALL_FOLLOW_ENABLE","data":"1","key":"2"}` as DP 2 value
2. **Test GET_LUCY_POSE**: Query robot position — useful for live map
3. **Test other DP IDs**: Send simple values on DP 3, 4, 8, etc. and watch for effects
4. **Test running modes**: Send `running_mode_with_dock` as a DP key

### On-robot experiments (via SSH):
5. **List ZMQ sockets**: `ls /data/local/tmp/` to find live IPC endpoints
6. **Sniff ZMQ traffic**: Use a Python ZMQ SUB socket to listen on `cloud/cloud_status_data` and capture what cloud_node sends when we issue MQTT commands
7. **Capture protobuf**: Record the raw bytes of CloudStatusDataItemMsg to reverse the field format
8. **Try sending protobuf**: Craft a minimal protobuf and send to guidance_node's RPC endpoint

---

## Key Files

| File | Purpose |
|------|---------|
| `mqtt_capture/capture_server.py` | MQTT server, command sending |
| `mqtt_capture/lucy_control.py` | CLI control interface |
| `mqtt_capture/send_command.py` | Low-level command sender |
| `lucy_re/09_mqtt_commands.md` | MQTT command protocol reference |
| `lucy_re/05_cloud_protocol.md` | Cloud protocol, DP keys, downdps format |
| `lucy_re/04_mcu_protocol.md` | MCU TBot API, SetMove/SetWallFollow |
| `lucy_re/03_zeromq_services.md` | ZMQ IPC topology, all endpoints |
| `lucy_re/02_message_protocol.md` | ServiceMsg protobuf, encryption layers |

---

## Cross-References

- [09_mqtt_commands.md](09_mqtt_commands.md) — Confirmed working MQTT commands
- [05_cloud_protocol.md](05_cloud_protocol.md) — Cloud protocol, DP upload/download
- [04_mcu_protocol.md](04_mcu_protocol.md) — MCU serial protocol, TBot API
- [03_zeromq_services.md](03_zeromq_services.md) — Full ZMQ IPC map
- [02_message_protocol.md](02_message_protocol.md) — Protobuf message formats
- [10_local_control_plan.md](10_local_control_plan.md) — Platform development plan
