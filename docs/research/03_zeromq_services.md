# Phase 3: ZeroMQ Service Mapping

## Overview

Lucy uses ZeroMQ 4.3.0 for all inter-process communication. There are two distinct transport layers:

1. **Internal IPC** — UNIX domain sockets under `/data/local/tmp/`, used exclusively between the robot's own processes
2. **External TCP** — a small number of TCP-bound ZMQ sockets used for factory/calibration tooling and WiFi provisioning

The external TCP ports are **not** part of normal robot operation — they are calibration and provisioning interfaces.

---

## External TCP ZeroMQ Ports

### Port 5556 — Factory Calibration Data (`calibrate_node`)

| Property | Value |
|----------|-------|
| Process | `calibrate_node` (PID varies) |
| Transport | ZeroMQ ZMTP 2.0 over TCP |
| Socket type | PUB or PUSH (calibration data publisher) |
| Purpose | Streams calibration data (camera images, point clouds) to factory tooling workstation |
| Message format | Serialised protobuf `ServiceMsg` containing calibration frame data |
| Active? | Only when `calibrate_node` is running during factory calibration procedure |

**Data streams published:**
- Stereo calibration images (`log_writer_intrincis` → `stereo_calib_images/`)
- Extrinsics calibration images (`log_writer_extrincis` → `robot_calib_images/`)
- Height calibration images (`log_writer_heights` → `height_calib_images/`)
- Point cloud images (`log_writer_point_cloud` → `point_cloud_images/`)
- Verification images (`log_writer_verify` → `verify_calib_images/`)

**Confirmed source:** `config_calibrate_node.json` — `calibrate_node` binds this port.

---

### Port 5678 — WiFi Provisioning (`trifo.netconfig` Android APK)

| Property | Value |
|----------|-------|
| Process | `trifo.netconfig` Android system app (PID 947, not part of robot stack) |
| Transport | ZeroMQ ZMTP 2.0 over TCP |
| Socket type | ROUTER (binds); client connects as DEALER |
| Purpose | WiFi network setup and device provisioning from the Trifo Home app |
| Message format | Unknown — likely protobuf `ServiceMsg` or similar; possibly the QLCloud rolling XOR cipher applied |
| Encryption | Unknown; possibly plaintext given it's provisioning |

**Context:** This port is bound by the Android system application `com.trifo.netconfig` running as a system service, **not** by any process in the robot core stack (`/data/user/app/`). The `cloud_node` config references the netconfig WiFi service path at `/data/data/com.trifo.netconfig/cache/`.

The Trifo Home app connects to this port when setting up the robot's WiFi credentials. The robot must be in AP mode (hosting its own SSID) for initial provisioning.

**Confirmed source:** Live process list (Phase 1), cloud_node config, Phase 1 binary analysis.

---

### Port 7777 — Factory Tool REQ/REP (`calibrate_node`)

| Property | Value |
|----------|-------|
| Process | `calibrate_node` |
| Transport | ZeroMQ ZMTP 2.0 over TCP |
| Socket type | REP (server) |
| Purpose | Simple factory test handshake |
| Message format | Echoes first byte of any received message back to sender |
| Protocol | Trivial: send any byte, receive same byte back |

**Usage:** Factory tooling uses this as a "ping" to confirm the calibration node is alive and reachable before beginning a calibration sequence.

**Confirmed source:** Phase 1 live observation ("echoes first byte"); calibrate_node config.

---

### Port 12121 — Debug Agent (`debug_node`, **DISABLED in production**)

| Property | Value |
|----------|-------|
| Process | `debug_node` (node_launcher: false — not started by default) |
| Transport | TCP |
| Socket type | TCP agent (not ZeroMQ; likely raw TCP or HTTP) |
| Purpose | Developer visualisation and debug interface |
| Active? | **No** — disabled in `config_robot_node_manager.json` |

**Source:** `config_debug_node.json`: `"agent_port": 12121`; Phase 1 binary analysis found `StartAgent` function.

---

## External UDP Ports (Discovery, not ZeroMQ)

These are plain UDP sockets used by `calibrate_node` for factory device discovery — not ZeroMQ:

| Port | Direction | Data | Purpose |
|------|-----------|------|---------|
| 3888 | Multicast `239.0.1.1:3888` | `WhoIsTrifoV1` | Factory tool broadcasts to find robots on LAN |
| 3898 | UDP | `bot!<>?test#2` | Factory tool → robot: initiate calibration session |
| 3880 | UDP | Heartbeat data | Robot heartbeat to factory tool during calibration |

**Source:** `config_calibrate_node.json`:
```json
"bd_find_device_port":     3888,
"bd_calib_device_port":    3898,
"bd_device_heartbeat_port": 3880,
"bd_find_device_data":     "WhoIsTrifoV1",
"bd_calib_device_data":    "bot!<>?test#2"
```

---

## Internal ZeroMQ IPC (UNIX Domain Sockets)

All robot-internal process communication uses ZeroMQ over UNIX domain sockets. Socket paths live in `/data/local/tmp/` (confirmed from Phase 1 live enumeration).

### Naming Convention

**Pub/Sub topics:** socket path = topic name (e.g., `txen_driver/bot_data`)
**RPC endpoints:** `TrifoIPC_{node}-{purpose}_REQ` / `TrifoIPC_{node}-{purpose}_REP`

---

### Pub/Sub Socket Map

The following table lists all confirmed pub/sub topics derived from node config files and binary analysis:

| Topic (Socket Path) | Publisher | Subscribers | Content |
|---------------------|-----------|-------------|---------|
| `txen_driver/bot_data` | `sensor_node` | `guidance_node`, `slam_node`, `perception_node`, `cloud_node`, `calibrate_node` | Wheel odometry, cliff/bumper sensors, wheel speeds |
| `txen_driver/imu_data` | `sensor_node` | `slam_node` | IMU (accelerometer, gyroscope) |
| `txen_driver/robot_status` | `sensor_node` | `cloud_node`, `calibrate_node`, `debug_node` | Battery level, error codes, charging state |
| `txen_driver/robot_utility_command` | `guidance_node` | `sensor_node`, `calibrate_node` | Utility commands (lights, sounds, blower) |
| `txen_driver/audio_data` | `sensor_node` | `cloud_node`, `perception_node` | Microphone audio (2ch, 44100 Hz, 16-bit) |
| `lucy_camera/image_data` | `camera_node` | `perception_node`, `cloud_node`, `calibrate_node`, `offline_node` | RGB frames (NV12, 1920×1080) — notification only; pixel data via shared mem |
| `lucy_camera/depth_data` | `camera_node` | `perception_node`, `slam_node`, `calibrate_node`, `offline_node` | ToF depth / point cloud — notification only; data via shared mem |
| `lucy_camera/image_data_h264` | `camera_node` | `cloud_node` | H.264 encoded video stream |
| `lucy_camera/cg_encode_data` | `camera_node` | `cloud_node` | CG IR encoded data |
| `mapper/global_pose` | `slam_node` | `guidance_node`, `sensor_node`, `calibrate_node` | Robot pose (x, y, theta) in map frame |
| `mapper/map_T_odom` | `slam_node` | `guidance_node` | Map-to-odometry transform |
| `mapper/multi_layer_map` | `slam_node` | `guidance_node` | Full occupancy grid map (IPC notification; data via shared mem) |
| `visual_mapper/multi_layer_map` | `slam_node` | `guidance_node`, `cloud_node` | Visual map for cloud upload |
| `visual_mapper/mapper_response` | `slam_node` | `cloud_node` | Mapper state change responses |
| `visual_mapper/ogm_data` | `slam_node` | `debug_node` | Raw occupancy grid data |
| `point_cloud_preprocessor/filtered_sensor_data` | `perception_node` | `slam_node` | Filtered ToF scan (laser-scan-like) |
| `pcd_object_detection_actor/barrier_range_data` | `perception_node` | `guidance_node`, `slam_node` | 3D obstacle ranges from point cloud |
| `dl_object_detection_actor/barrier_range_data` | `perception_node` | `guidance_node`, `slam_node` | AI obstacle ranges from TFLite segmentation |
| `dl_object_detection_actor/percept_result_item` | `perception_node` | `cloud_node` | Full AI perception results (object classes) |
| `dock_detector/dock_data` | `perception_node` | `guidance_node` | Dock position and IR pattern |
| `dock_detector/barrier_range_data` | `perception_node` | `guidance_node`, `slam_node` | Obstacles in dock area |
| `stuck_detector/stuck_data` | `perception_node` | `guidance_node`, `slam_node` | Stuck detection signal |
| `planning_actor/motion_command` | `guidance_node` | `sensor_node`, `cloud_node`, `calibrate_node` | Wheel velocity commands (left/right speeds) |
| `planning_actor/clean_status` | `guidance_node` | `cloud_node` | Current cleaning mode/state |
| `planning_actor/mapper_control_info` | `guidance_node` | `slam_node`, `cloud_node` | Map control commands (save, load, reset) |
| `planning_actor/room_segmentation` | `guidance_node` | `cloud_node` | Room boundary segmentation data |
| `planning_actor/waypoints` | `guidance_node` | `debug_node` | Navigation waypoint list |
| `planning_actor/frontier` | `guidance_node` | `debug_node` | Exploration frontier points |
| `planning_actor/cloud_planning_params` | `cloud_node` | `guidance_node` | Cloud-sourced planning parameters |
| `planning_actor/planner_control_info` | `guidance_node` | — | Planner state info |
| `cloud_actor/mapper_control_info` | `cloud_node` | `slam_node` | Cloud-sourced map control commands |
| `cloud/cloud_status_data` | `cloud_node` | `guidance_node`, `sensor_node` | Cloud → robot command frame (parsed from MQTT) |
| `cloud/cloud_stream_status_data` | `cloud_node` | — | Video stream status |
| `semantic_map_actor/semantic_instances` | `offline_node` | `cloud_node` | Detected semantic objects (furniture etc.) |
| `semantic_map_actor/semantic_map_status` | `offline_node` | `cloud_node` | Semantic map processing status |
| `pcd_object_detection_actor/cloud_detection_params` | `cloud_node` | `perception_node` | Cloud-sourced detection parameters |
| `bot/camera_sync` | `camera_node`/`sensor_node` | `slam_node` | Camera–IMU time synchronisation |

---

### RPC Endpoints (TrifoIPC REQ/REP)

All RPC uses ZeroMQ REQ/REP pairs over UNIX IPC. The `manager_node` (or `cloud_node`) acts as REQ client; the target node binds the REP socket.

| Endpoint | REQ Client | REP Server | Purpose |
|----------|-----------|-----------|---------|
| `TrifoIPC_sensor_node-robot_control_REQ/REP` | `manager_node` | `sensor_node` | Direct robot control (start/stop, mode) |
| `TrifoIPC_sensor_node-mode_switch_REQ/REP` | `manager_node` | `sensor_node` | Mode state machine transitions |
| `TrifoIPC_planning_actor-motion_command_REQ/REP` | `cloud_node` | `guidance_node` | Direct motion velocity commands |
| `TrifoIPC_planning_actor-mapper_control_info_REQ/REP` | `cloud_node` | `guidance_node` | Map control (save/load/reset) |
| `TrifoIPC_cloud_actor-mapper_control_info_REQ/REP` | External | `cloud_node` | Cloud-sourced map commands |
| `TrifoIPC_planning_actor-cloud_planning_params_REQ/REP` | `cloud_node` | `guidance_node` | Cloud planning parameters |
| `TrifoIPC_pcd_object_detection_actor-cloud_detection_params_REQ/REP` | `cloud_node` | `perception_node` | Cloud detection parameters |
| `TrifoIPC_cloud-firmware_ota_data_from_bot_REQ/REP` | `sensor_node` | `cloud_node` | MCU firmware info for OTA |
| `TrifoIPC_cloud_actor-manual_controller_info_REQ/REP` | `cloud_node` | `guidance_node` | Manual drive commands from app |
| `TrifoIPC_cloud-cloud_stream_status_data_REQ/REP` | `cloud_node` | `cloud_node` | Video stream control |
| `TrifoIPC_txen_driver-robot_utility_command_REQ/REP` | `cloud_node` | `sensor_node` | Utility commands (LEDs, voice, blower) |
| `TrifoIPC_txen_driver-calibrate_data_to_bot_REQ/REP` | `calibrate_node` | `sensor_node` | Calibration data forwarding to MCU |
| `TrifoIPC_mapper-mapping_state_update_REQ/REP` | `manager_node` | `slam_node` | SLAM state control |
| `TrifoIPC_slam_node-motion_detect_control_REQ/REP` | `manager_node` | `slam_node` | Motion detection enable/disable |
| `TrifoIPC_lucy_camera_node-camera_control_info_REQ/REP` | `cloud_node`/`calibrate_node` | `camera_node` | Camera parameter control |
| `TrifoIPC_{node}_REQ/REP` | `manager_node` | Each node | Generic node RPC (health check, control) |
| `TrifoIPC_{node}-mode_switch_REQ/REP` | `manager_node` | Each node | Mode switch broadcast to all nodes |

**RPC message format**: Each request/reply carries a protobuf `RPCRequestBase` / `RPCReplyBase` envelope wrapping a serialised `ServiceMsg`. See [Phase 2](02_message_protocol.md) for details.

---

## Shared Memory (High-Bandwidth Data)

Large data payloads (camera frames, maps) bypass ZeroMQ entirely and use POSIX shared memory with named semaphores. The ZMQ message serves only as a notification that new data is available.

| Shared Memory Name | Semaphore Name | Producer | Consumers | Data |
|-------------------|----------------|----------|-----------|------|
| `/dev/shm/TrifoSHM_lucy_camera-image_data` | `TrifoSemaphore_lucy_camera-image_data` | `camera_node` | `perception_node`, `cloud_node`, `offline_node` | NV12 YUV, 1920×1080 |
| `/dev/shm/TrifoSHM_lucy_camera-depth_data` | `TrifoSemaphore_lucy_camera-depth_data` | `camera_node` | `perception_node`, `slam_node` | ToF point cloud |
| `/dev/shm/TrifoSHM_lucy_camera-cg_encode_data` | `TrifoSemaphore_lucy_camera-cg_encode_data` | `camera_node` | `cloud_node` | CG IR encoded |
| `/dev/shm/TrifoSHM_lucy_camera-image_data_h264` | `TrifoSemaphore_lucy_camera-image_data_h264` | `camera_node` | `cloud_node` | H.264 video |
| `/dev/shm/TrifoSHM_mapper-multi_layer_map` | `TrifoSemaphore_mapper-multi_layer_map` | `slam_node` | `guidance_node` | Occupancy grid map |
| `/dev/shm/TrifoSHM_visual_mapper-multi_layer_map` | `TrifoSemaphore_visual_mapper-multi_layer_map` | `slam_node` | `cloud_node` | Visual map |
| `/dev/shm/TrifoSHM_dl_object_detection_actor-percept_result_item` | `TrifoSemaphore_dl_object_detection_actor-percept_result_item` | `perception_node` | `cloud_node` | AI perception results |

---

## Port Summary Table

| Port | Protocol | Process | Active | Purpose |
|------|----------|---------|--------|---------|
| 22 | SSH (TCP) | `dropbear` | Always | Root shell |
| 5556 | ZMQ ZMTP 2.0 TCP | `calibrate_node` | Factory only | Calibration data stream |
| 5678 | ZMQ ZMTP 2.0 TCP | `trifo.netconfig` APK | Always | WiFi provisioning |
| 7777 | ZMQ ZMTP 2.0 TCP | `calibrate_node` | Factory only | Factory tool ping/handshake |
| 3888 | UDP multicast | `calibrate_node` | Factory only | Device discovery |
| 3898 | UDP | `calibrate_node` | Factory only | Calibration session initiation |
| 3880 | UDP | `calibrate_node` | Factory only | Heartbeat during calibration |
| 12121 | TCP | `debug_node` | **Disabled** | Developer debug agent |

---

## Key Findings

1. **The external TCP ZMQ ports are not operational interfaces** — they are factory/calibration tools. There is no normal-operation TCP ZMQ interface for sending commands to Lucy.

2. **Port 5678 is the only always-on external interface** after SSH, and it is owned by the Android WiFi provisioning app, not the robot core stack.

3. **All robot control happens over IPC** — the correct approach for local control is to become a peer process on the UNIX domain socket bus, or to send commands via the `cloud/cloud_status_data` IPC topic (as the cloud_node normally does after parsing MQTT messages).

4. **The simplest local control path** would be to replace `cloud_node` with a local process that:
   - Publishes `CloudStatusDataItemMsg` protobuf messages to the `cloud/cloud_status_data` IPC socket
   - Subscribes to status topics to read robot state
   - This requires running on the robot itself with access to `/data/local/tmp/`

---

## Cross-References

- See [Phase 1](01_process_architecture.md) for process topology and which processes are spawned
- See [Phase 2](02_message_protocol.md) for the `ServiceMsg` protobuf format carried by all ZMQ messages
- See [Phase 4](04_mcu_protocol.md) for the serial protocol between processes and the STM32 MCU
- See [Phase 5](05_cloud_protocol.md) for how `cloud_node` generates the `cloud/cloud_status_data` IPC messages from MQTT
