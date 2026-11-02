# Phase 12: SHM, ZMQ IPC, and Camera System

**Date:** 2026-03-27
**Status:** Research complete, implementation pending

This document covers three interconnected subsystems discovered during live-session reverse engineering of the Trifo Lucy robot vacuum: shared memory ring buffers, the ZMQ inter-process communication topology, and the full camera hardware/software stack. Together, these provide a path to MQTT-free local control with live video and map streaming.

---

## Table of Contents

1. [Shared Memory Segments](#1-shared-memory-segments)
2. [Camera Hardware](#2-camera-hardware)
3. [ZMQ IPC Topology](#3-zmq-ipc-topology)
4. [Camera Access Approaches](#4-camera-access-approaches)
5. [Key Implications](#5-key-implications)
6. [Protobuf Protocol Definitions](#6-protobuf-protocol-definitions-extracted-2026-03-27)

---

## 1. Shared Memory Segments

Seven SHM segments exist in `/dev/shm/`, all using the **TrifoSemaphore multi-buffer ring** format. Each segment contains a header (semaphore metadata, buffer count, write index) followed by N fixed-size slots. Writers rotate through slots; readers check the semaphore to find the latest complete frame.

### 1.1 Segment Inventory

| Segment | Size | Buffers | Writer | Content |
|---------|------|---------|--------|---------|
| `mapper-multi_layer_map` | 125.8 MB | 2 | slam_node | Protobuf multi-layer occupancy grids |
| `visual_mapper-multi_layer_map` | 31.5 MB | 2 | guidance_node | Visual mapper grid output |
| `lucy_camera-image_data` | 12.6 MB | 3 | camera_node | Raw NV12 1920x1080 RGB frames |
| `lucy_camera-image_data_h264` | 12.6 MB | 4 | camera_node | H.264 NAL units (hardware-encoded) |
| `lucy_camera-depth_data` | 3.2 MB | 3 | camera_node | uint16 depth + point cloud (224x172) |
| `lucy_camera-cg_encode_data` | 3.2 MB | 3 | camera_node | H.264 encoded ToF/CG IR stream |
| `dl_object_detection-percept_result_item` | 3.2 MB | 2 | perception_node | Detection results (zeros when idle) |

### 1.2 Map Segment Detail

The `mapper-multi_layer_map` segment contains protobuf-serialized multi-layer grids with **4 layers**:

| Layer | Purpose |
|-------|---------|
| `scan_map` | Primary lidar occupancy grid |
| `barrier_map` | Obstacle/barrier classification |
| `barrier_height_scan_map` | Height-filtered obstacle map |
| `sensor_map` | Combined sensor fusion output |

**Grid parameters:**

| Parameter | Value |
|-----------|-------|
| cell_size | 0.025 m (2.5 cm) |
| width | 226 cells |
| height | 167 cells |
| origin_x | 3.238 m |
| origin_y | 2.562 m |

**Cell value encoding:**

| Value | Meaning |
|-------|---------|
| `0x80` (128) | Unknown / unexplored |
| `0x74` (116) | Free space |
| `0xB1` (177) | Occupied / obstacle |

**Height ranges** (from `pose_graph.lua`, `num_of_map_layer=3`):

| Range | Min (cm) | Max (cm) | Purpose |
|-------|----------|----------|---------|
| 1 | 8 | 70 | Full obstacle detection |
| 2 | 8 | 13 | Low obstacle detection |
| 3 | 5 | 9 | Ground-level detection |

This is significant: the live map data in SHM is a **raw probability grid**, which bypasses the unsolved OGM file encoding problem entirely. Reading this segment gives real-time map access without needing to decode the on-disk `.ogm` format.

---

## 2. Camera Hardware

The Lucy has two cameras: a standard RGB visual camera and a time-of-flight (ToF) depth camera, both connected via MIPI CSI to the RK3399's dual ISPs.

### 2.1 Visual Camera (RGB)

| Property | Value |
|----------|-------|
| Sensor | OV2718 (OmniVision, 2MP) |
| Interface | MIPI CSI to ISP1 |
| V4L2 devices | `/dev/video0` (mainpath), `/dev/video1` (selfpath) |
| Resolution | 1920 x 1080 |
| Output format | NV12 (Y plane + interleaved UV) |
| Frame size | 3,110,400 bytes |
| Sensor raw format | SBGGR10 (10-bit Bayer) |

**Intrinsics:**

| Parameter | Value |
|-----------|-------|
| cx | 992.15 |
| cy | 548.17 |
| fx | 1520.08 |
| fy | 1520.08 |

### 2.2 Depth Camera (ToF)

| Property | Value |
|----------|-------|
| Sensor | Sunny ToF (pmd spectre3 technology) |
| Interface | MIPI CSI to ISP2 |
| V4L2 devices | `/dev/video4` (mainpath), `/dev/video5` (selfpath) |
| Raw resolution | 224 x 1720 at BG12 (12-bit Bayer) |
| Raw structure | 10 sub-frames of 172 lines each (ToF modulation phases) |
| Processed resolution | 224 x 172 |
| Processed format | uint16 depth values |
| Libraries | `libtofapi.so`, `libdepthcal.so`, `libspectre3.so`, `libspectre_processing.so` |

The raw 224x1720 frame is not a single image -- it is 10 vertically stacked 224x172 sub-frames capturing different ToF modulation phases. The spectre3 library processes these into a single 224x172 depth map.

**Intrinsics:**

| Parameter | Value |
|-----------|-------|
| cx | 112.16 |
| cy | 85.39 |
| fx | 210.91 |
| fy | 210.91 |

### 2.3 Stereo Calibration

RGB-to-depth translation vector: **[11.69, -0.17, 2.34] mm**

This enables RGBD fusion -- projecting depth pixels into the RGB frame for colored point clouds or depth-overlaid images.

### 2.4 H.264 Hardware Encoding

Both RGB and ToF IR streams are hardware-encoded via the **Rockchip MPP** (Media Process Platform):

- Device: `/dev/vpu_service`
- Library: `libmpp.so`
- RGB stream: H.264 NAL units written to `lucy_camera-image_data_h264` SHM
- ToF IR stream: H.264 NAL units written to `lucy_camera-cg_encode_data` SHM

The H.264 encoding happens continuously while camera_node is running. Frames are already compressed and ready for network transport.

### 2.5 Camera Configuration

**Config file:** `/data/user/app/node_config/config_camera_node.json`

Key settings:

| Setting | Default | Notes |
|---------|---------|-------|
| `capture_point_cloud` | `true` | Enables depth point cloud generation |
| `capture_rgb_image` | `true` | Enables RGB frame capture |
| `enable_encoder` | `true` | H.264 encoding of RGB stream |
| `enable_encoder_cg` | `true` | H.264 encoding of ToF IR stream |
| `log_data` | `false` | **Set to `true` to dump frames to disk** |
| `log_data_fps` | 5 | Frame dump rate when log_data is enabled |

Setting `log_data: true` is the quickest way to get camera frames saved to the filesystem without writing any code.

### 2.6 Existing Camera Artifacts on Device

| Path | Contents |
|------|----------|
| `/data/user/app/camera_validates/` | RGBD confidence PNGs (224x172, 16-bit), point clouds (`.pcd`, ~462 KB each), YUV captures |
| `/data/user/app/stereo_calib_images/` | Stereo calibration YUV images (3,110,400 bytes = 1920x1080 NV12) |

These files confirm the frame formats and resolutions documented above.

---

## 3. ZMQ IPC Topology

Nine processes communicate via approximately **37 REQ/REP** and **19 PUB/SUB** ZMQ channels. All use Unix domain sockets located in `/data/local/tmp/`.

### 3.1 Channel Naming Conventions

Two patterns are used:

| Pattern | Socket Type | Naming | Purpose |
|---------|-------------|--------|---------|
| Command/Control | REQ/REP (DEALER/ROUTER) | `TrifoIPC_{owner}-{channel}_{REQ\|REP}` | Protobuf `ServiceMsg` RPC |
| Data Streaming | PUB/SUB | `{owner}-{data_type}` | High-throughput sensor data |

### 3.2 Process Roles

| Process | Role | Key Responsibilities |
|---------|------|---------------------|
| **manager_node** | Orchestrator | Mode switching, lifecycle management for all nodes |
| **sensor_node** | MCU interface | STM32F407 communication; publishes `bot_data`, `imu_data`, `robot_status` |
| **slam_node** | SLAM engine | Google Cartographer; publishes `global_pose`, `map_T_odom`; writes map SHM |
| **guidance_node** (planning_actor) | Path planner | Navigation, coverage planning; publishes `clean_status`, `waypoints` |
| **cloud_node** (cloud_actor) | MQTT bridge | QLCloud SDK, smart speaker commands; owns `manual_controller_info`, `mapper_control_info` |
| **perception_node** | Obstacle detection | Camera-based detection; publishes `barrier_range_data`, `dock_data`, `stuck_data` |
| **camera_node** (lucy_camera_node) | Stereo camera | RGB + ToF capture/processing; owns `camera_control_info` |

### 3.3 TCP Endpoints

| Endpoint | Purpose |
|----------|---------|
| `tcp://127.0.0.1:5555` | Internal driver/writer communication |
| `tcp://127.0.0.1:5678` | Factory test tool / WiFi provisioning |

### 3.4 High-Value Control Channels

These are the ZMQ channels most relevant for building local control without MQTT:

| # | Channel | Message Type | Purpose |
|---|---------|-------------|---------|
| 1 | `TrifoIPC_sensor_node-robot_control` | `RobotControlCommandMsg` | **Direct motor control** -- wheel speeds, brush motors |
| 2 | `TrifoIPC_planning_actor-motion_command` | `MotionCommandItemMsg` | **Velocity commands** -- linear/angular velocity targets |
| 3 | `TrifoIPC_txen_driver-robot_utility_command` | (utility msg) | **MCU utility** -- blower speed, brush on/off, side brush |
| 4 | `TrifoIPC_cloud_actor-manual_controller_info` | (manual control msg) | **Joystick/manual control emulation** -- what MQTT commands use internally |
| 5 | `TrifoIPC_lucy_camera_node-camera_control_info` | (camera control msg) | **Camera control** -- start/stop capture, change settings |
| 6 | `TrifoIPC_cloud-cloud_stream_status_data` | (stream status msg) | **Cloud stream control** -- enable/disable video upload |

Channel 4 (`manual_controller_info`) is particularly interesting: this is the internal endpoint that cloud_node writes to when it receives MQTT smart speaker commands. Connecting directly to this channel would replicate MQTT command functionality with sub-millisecond latency and zero cloud dependency.

Channel 1 (`robot_control`) goes even deeper, providing raw motor control at the sensor_node/MCU level. This enables behaviors not possible through the smart speaker command set (custom velocities, precise movements).

---

## 4. Camera Access Approaches

Ranked by practicality and invasiveness:

### Approach 1: SHM Ring Buffer Reader (Recommended)

**Invasiveness:** None -- read-only, camera_node continues normally

Read H.264 NAL units from `lucy_camera-image_data_h264` or raw NV12 from `lucy_camera-image_data`. Requires reversing the TrifoSemaphore header format to locate the current write slot and frame boundaries within each buffer.

**Pros:** Zero disruption, real-time, works while robot operates normally
**Cons:** Must reverse TrifoSemaphore header format
**Output:** H.264 stream (network-ready) or raw NV12 frames

### Approach 2: Enable log_data in Camera Config

**Invasiveness:** Minimal -- config change only

Edit `/data/user/app/node_config/config_camera_node.json`, set `log_data: true` and `log_data_fps: 5`. Restart camera_node. Frames dump to disk.

**Pros:** No code required, immediate results
**Cons:** Disk I/O overhead, limited FPS, fills storage over time
**Output:** Individual frame files on the robot's filesystem

### Approach 3: On-Device Relay Server

**Invasiveness:** Low -- deploy a small binary/script

A lightweight program on the robot reads H.264 from SHM and serves it over TCP or HTTP. Clients connect from the network to receive the live stream.

**Pros:** Clean network interface, standard streaming protocols
**Cons:** Requires deploying and running additional software on-device
**Output:** Network-accessible H.264 stream (e.g., RTSP, HTTP-FLV, raw TCP)

### Approach 4: Direct V4L2 Capture

**Invasiveness:** High -- must stop camera_node

Stop camera_node, then capture directly from `/dev/video0` (RGB) or `/dev/video4` (ToF) using `v4l2-ctl` or a custom V4L2 program.

**Pros:** Full control over capture parameters
**Cons:** Disrupts all robot vision (SLAM, obstacle detection, etc.)
**Output:** Raw frames from the V4L2 device

### Approach 5: ZMQ Subscriber

**Invasiveness:** None -- subscribe to camera data topics

Connect a ZMQDataSubscriber to the camera PUB/SUB topics to receive frame data or detection results.

**Pros:** Uses the existing IPC framework
**Cons:** Need to identify exact topic names and message formats
**Output:** Protobuf-wrapped frame data

---

## 5. Key Implications

### Live Maps Without OGM Decoding

The `mapper-multi_layer_map` SHM segment contains the live occupancy grid as a raw probability grid with straightforward cell values (0x80/0x74/0xB1). This completely bypasses the unsolved OGM file format encoding problem documented in `ogm_format_research.md`. For real-time map display, SHM is the correct approach.

### Camera Frames Are Already Network-Ready

The H.264 SHM segments (`image_data_h264`, `cg_encode_data`) contain hardware-encoded NAL units. A relay server only needs to read these buffers and forward them over TCP -- no transcoding, no CPU-intensive encoding. The RK3399's MPP hardware encoder is already doing the work.

### MQTT-Free Local Control

The ZMQ control channels (especially `manual_controller_info` and `robot_control`) enable complete robot control without any MQTT involvement. This means:

- No dependency on the capture_server.py MQTT proxy
- Sub-millisecond command latency (Unix domain socket vs. TCP)
- Access to motor-level control not exposed through smart speaker commands
- A small on-robot agent could provide a local REST/WebSocket API backed by ZMQ

### Unified On-Robot Agent

All three capabilities (maps, cameras, control) converge on a single architecture: a lightweight on-robot agent that:

1. Reads map SHM for live occupancy grids
2. Reads camera SHM for H.264 video streams
3. Writes to ZMQ control channels for robot commands
4. Exposes everything over a local network API

This agent would make the robot fully self-contained with no cloud dependency whatsoever.

---

## 6. Protobuf Protocol Definitions (Extracted 2026-03-27)

Complete protobuf message definitions were extracted from `libtrifo_core_items.so` (4.9MB) by locating embedded `FileDescriptorProto` serialized descriptors. 14 .proto files were found:

- `proto/item_msg.proto` — 17 messages (core types, control items, sensor data)
- `proto/node_msg.proto` — 7 messages (ServiceMsg envelope, RPC base, system status)
- `proto/planning_msg.proto` — 7 messages (VelocityCommand, MoveCommand, RotateCommand, etc.)
- `proto/cloud_map_layer_msg.proto` — 2 messages (CloudGridMsg, CloudMultiMapLayerMsg)
- `proto/cloud_map_manage_msg.proto` — 6 messages (map management, room segmentation)
- `proto/cloud_status_data_msg.proto` — 4 messages (cloud mode, stream, blower, voice)
- `proto/cv_util_msg.proto` — 6 messages (Mat, Vector, Rect, etc.)
- `proto/map_layer_msg.proto` — 1 message (GridMsg)
- `proto/map_msg.proto` — 9 messages (sparse map, features, SLAM data)
- `proto/obstacle_msg.proto` — 2 messages (detected objects)
- `proto/robot_status_data_msg.proto` — 2 messages (battery, exceptions)
- `proto/robot_utility_command_msg.proto` — 1 message (RobotVoiceCommandMsg)
- `proto/semantic_mapping_msg.proto` — 2 messages (voxel blocks, label counts)
- `proto/sensor_data_msg.proto` — 9 messages (depth, IMU, pose, image, point cloud)

### Key Control Messages

**Direct motor control (via ZMQ `motion_command` channel):**
```
VelocityCommandMsg { float left_nominal_speed=1, float right_nominal_speed=2, uint64 maintain_time=3, uint32 command_id=4 }
MoveCommandMsg { int32 direction=1, float wheel_speed=2, float distance=3, float target_heading=4, bool default_heading=5, uint32 command_id=6 }
RotateCommandMsg { int32 heading_type=1, float left/right_nominal_speed=2/3, float target_heading=4, uint32 command_id=5 }
TargetPoseCommandMsg { float wheel_speed=1, float target_x=2, float target_y=3, uint32 command_id=4 }
WallFollowCommandMsg { int32 direction=1, float wheel_speed=2, uint32 command_id=3 }
DockCommandMsg { uint32 command_id=1 }
StopCommandMsg { uint32 command_id=1 }
```

**ServiceMsg (master RPC envelope, field numbers):**
1=type, 2=system_status, 3=system_mode, 4=motion_command, 5=robot_utility_command, 6=mapper_control_info, 7=test_msg, 8=cloud_status, 9=reloc_result, 10=calibrate_data, 11=planning_layer, 12=camera_control_info, 13=sensor_data_msg, 14=camera_calib_info, 15=command_status, 16=manual_controller_info, 17=manual_control_info, 18=multilayer_grid_map, 19=list_of_multilayer_grid_map

**Joystick control:**
```
ManualControlInfoItemMsg { uint32 command=1, double wheel_speed=2, Affine2DMsg pose=3, uint32 vertex_count=4 }
PlannerControlInfoItemMsg { int32 command=1, double wheel_speed=2, double left_wheel_speed=3, double right_wheel_speed=4, double x=5, double y=6, double theta=7 }
```

### Full .proto File
Complete definitions saved to `mqtt_capture/lucy_proto.proto`

### Implications for Local Control
With these protobuf definitions, an on-robot ZMQ agent can:
1. Send VelocityCommandMsg to directly control wheel speeds
2. Send TargetPoseCommandMsg to navigate to coordinates on the map
3. Send WallFollowCommandMsg for edge cleaning
4. Read MultiLayerGridMapItemMsg for live map updates
5. Wrap everything in ServiceMsg → RPCRequestBase for the ZMQ channels
6. Use CloudBlowerModeDataMsg to set suction level via cloud_status

This is the complete protocol needed for MQTT-free local control.

---

## 7. Live Data Verification (2026-03-28)

All major data streams verified working while Lucy is docked:

### Live Camera Frame from SHM
- Read 3.1MB NV12 frame directly from `/dev/shm/TrifoSemaphore_lucy_camera-image_data` at offset 0x2000
- Successfully converted NV12→RGB and saved as PNG
- Shows Lucy's real-time view from dock (furniture, floor, low-light scene)
- Frame data is **always available** — no need to trigger capture or start cleaning

### Live IMU Data (100Hz)
- Decoded from sensor_node ZMQ PUB on fd 112/113/115 (45-byte messages)
- Format: `SensorDataItemMsg` → key=8 → `ImuDataMsg` (6 float32 fields + varint timestamp)
- Fields: accel_x, accel_y, accel_z (float32), gyro_x, gyro_y (float32), timestamp (varint)
- accel_z ≈ -35.19 (raw ADC units, not m/s² — needs scale factor ~3.59)
- gyro values near zero when docked (~0.015 rad/s)

### Live Robot Pose (50Hz)
- Decoded from slam_node ZMQ PUB on fd 129 (39-byte messages)
- Format: `Pose2DItemMsg` with double x, y, theta + varint timestamps
- Docked position: x=0.649m, y=-0.053m, theta=3.71 rad (212.8°)
- Successfully overlaid on SHM grid map — position matches dock area

### Live Robot Status (3Hz)
- Decoded from sensor_node ZMQ PUB on fd 118 (20-byte messages)
- Shows charging_status=1 (charging) while docked

### Volume Control Confirmed
- `setVolume:50` + `volumeRelative:10` = volume now 60 (was 19)
- Both commands work as expected

### Map Grid Verified
- SHM scan_map: 382×435 cells at 0.025m/cell = 9.55m × 10.88m
- Raw cell values: 0x80=unknown (80%), 0x00=free (12%), 0xb1=occupied (3.6%)
- barrier_map: same dimensions, 10 bytes/cell (10 height layers)
- Saved color-coded map visualization as PNG

---

## References

- Camera config: `/data/user/app/node_config/config_camera_node.json`
- SLAM config: `/data/user/app/slam_config/pose_graph.lua`
- SHM segments: `/dev/shm/`
- ZMQ sockets: `/data/local/tmp/`
- OGM format research: `lucy_re/ogm_format_research.md`
- Command architecture: `lucy_re/command_architecture.md`
- MQTT command reference: `lucy_re/09_mqtt_commands.md`
