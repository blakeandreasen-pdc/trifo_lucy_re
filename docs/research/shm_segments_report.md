# Lucy SHM Segments & IPC Report

Investigation date: 2026-03-27

## Summary

Lucy uses 7 shared memory segments (all in `/dev/shm/`) and ~80 ZMQ IPC sockets (in `/data/local/tmp/`) for inter-process communication between its nodes. The SHM segments use a custom `TrifoSemaphore` multi-buffer ring format for lock-free producer/consumer data sharing.

## Key Processes

| PID | Process | Role |
|-----|---------|------|
| 1247 | manager_node | Process supervisor |
| 1281 | slam_node | SLAM + mapping |
| 1283 | perception_node | Object detection, point clouds |
| 1284 | sensor_node | MCU interface (wheels, IMU, bumpers) |
| 1285 | guidance_node | Path planning + navigation |
| 19534 | camera_node | Camera capture (RGB + depth + IR) |
| 25697 | cloud_node | Cloud communication (MQTT) |

## TrifoSemaphore Format

All SHM segments share a common header structure:

```
Offset  Size   Field
0x00    u32    num_buffers (2, 3, or 4)
0x0C    u32    flags (always 1)
0x14    u32    active_slot (always 1)
0x3C    u32    8192 (constant, purpose TBD)
0x68    u64    write_sequence_counter (changes per update)
0x70    u64    read_sequence_counter
0x78+   16B*N  slot_table entries (0xFFFFFFFF = unused)
```

After the control header (likely 24 bytes global + slot metadata), the data payload begins. Each slot contains one complete frame/snapshot of the data.

---

## SHM Segment Details

### 1. mapper-multi_layer_map (125,833,464 bytes)

**Purpose:** Live occupancy grid map from SLAM
**Writer:** slam_node (PID 1281)
**Reader:** guidance_node (PID 1285)
**Buffers:** 2 (double-buffered)
**Per-slot:** ~62.9 MB

**Layers** (protobuf-serialized, 4 layers per slot):

| Layer | Encoding | Notes |
|-------|----------|-------|
| `scan_map` | uint8 per cell | Primary occupancy grid. 0x80=unknown (0.5 prob), <0x80=free, >0x80=occupied |
| `barrier_map` | multi-byte per cell | Obstacle probability + metadata. Default = 0.5 for unvisited |
| `barrier_height_scan_map` | TBD | Height-segmented barrier data |
| `sensor_map` | TBD | Sensor coverage / cleaning progress map |

**Protobuf grid header fields (per layer):**
- field 1 (double): `cell_size` = 0.025m (25mm)
- field 2 (varint): `width` = 226 cells
- field 3 (varint): `height` = 167 cells
- field 4 (double): `origin_x` = 3.238m
- field 5 (double): `origin_y` = 2.562m
- Grid physical size: **5.65m x 4.18m** (grows dynamically as robot explores)

**Height layers** (from Lua config `layered_map_height_range`):
1. 8-70cm (full range)
2. 8-13cm (low obstacles like thresholds)
3. 5-9cm (ground-level obstacles)

Grid probability uses log-odds (Cartographer-style):
- `grid_prob_clamp_max`: 0.999
- `grid_prob_clamp_min`: 0.5
- `hit_probability`: 0.7
- `miss_probability`: 0.45
- Resolution: 0.025m (from `trajectory_builder_2d.lua`)

---

### 2. visual_mapper-multi_layer_map (31,461,624 bytes)

**Purpose:** Display/cloud-upload version of the map
**Writer:** guidance_node (PID 1285)
**Readers:** guidance_node (self), cloud_node (PID 25697)
**Buffers:** 2 (double-buffered)
**Per-slot:** ~15.7 MB

**Layers** (4 layers per slot):

| Layer | Cell Size | Notes |
|-------|-----------|-------|
| `scan_map` | 0.025m | Same resolution as SLAM map |
| `barrier_map` | 0.05m | Half-resolution barrier view |
| `sensor_map` (x2) | 0.05m | Two sensor map instances |

These cell sizes come from `config_guidance_node.json`:
- `visual_scan_map_cell_size`: 0.025
- `visual_sensor_map_cell_size`: 0.05
- `visual_barrier_map_cell_size`: 0.05

---

### 3. lucy_camera-image_data (12,587,256 bytes)

**Purpose:** Live RGB camera frames
**Writer:** camera_node (PID 19534)
**Readers:** perception_node (PID 1283)
**Buffers:** 3 (triple-buffered)
**Per-slot:** ~4.2 MB

**Format:** YUV422 (NV12), 1920x1080 pixels
- 1920 * 1080 * 2 = 4,147,200 bytes raw pixel data
- ~48 KB per-slot metadata header
- Topic: `lucy_camera/image_data`

Data at offset 0x2000 contains visible grayscale pixel values (luminance channel), confirming active camera capture.

---

### 4. lucy_camera-image_data_h264 (12,587,256 bytes)

**Purpose:** H.264 encoded video stream for cloud
**Writer:** camera_node (PID 19534)
**Reader:** cloud_node (PID 25697)
**Buffers:** 4 (quad-buffered, extra for encode latency)
**Per-slot:** ~3.1 MB

**Format:** H.264 NAL units (variable-length compressed frames)
- Topic: `lucy_camera/image_data_h264`
- Data contains raw H.264 bitstream (no container)

---

### 5. lucy_camera-depth_data (3,150,072 bytes)

**Purpose:** ToF depth camera frames
**Writer:** camera_node (PID 19534)
**Reader:** perception_node (PID 1283)
**Buffers:** 3 (triple-buffered)
**Per-slot:** ~1.05 MB

**Format:** uint16 depth values, likely 960x540 resolution
- 960 * 540 * 2 = 1,036,800 bytes + ~13 KB metadata
- Topic: `lucy_camera/depth_data`
- Values are small integers (0-3 range in idle), representing depth in mm or similar

---

### 6. lucy_camera-cg_encode_data (3,150,072 bytes)

**Purpose:** CG (center-ground) IR sensor encoded data
**Writer:** camera_node (PID 19534)
**Reader:** cloud_node (PID 25697)
**Buffers:** 3 (triple-buffered)
**Per-slot:** ~1.05 MB

**Format:** Encoded IR image data (CG = center ground IR projector)
- Topic: `lucy_camera/cg_encode_data`
- Data appears compressed/encoded (high entropy bytes)
- Camera config: `cg_ir_auto_exposure: true`, `cg_ir_exposure: 650`

---

### 7. dl_object_detection_actor-percept_result_item (3,150,072 bytes)

**Purpose:** Deep learning object detection results
**Writer:** perception_node (PID 1283) - currently INACTIVE
**Reader:** cloud_node (PID 25697)
**Buffers:** 2 (double-buffered)
**Per-slot:** ~1.6 MB

**Status:** All zeros in data area when robot is idle. Populates during cleaning with detected objects (pets, shoes, cables, etc.)

---

## ZMQ IPC Sockets (/data/local/tmp/)

### Data Streams (PUB/SUB, no TrifoIPC_ prefix)

| Socket | Producer | Data |
|--------|----------|------|
| `txen_driver-bot_data` | sensor_node | Wheel odometry + encoder |
| `txen_driver-imu_data` | sensor_node | IMU (accel + gyro) |
| `txen_driver-robot_status` | sensor_node | MCU status reports |
| `txen_driver-audio_data` | sensor_node | Audio stream |
| `bot-camera_sync` | sensor_node | Camera-odometry synchronization |
| `mapper-global_pose` | slam_node | Robot pose in map frame |
| `mapper-map_T_odom` | slam_node | Map-to-odometry transform |
| `planning_actor-clean_status` | guidance_node | Cleaning state |
| `planning_actor-waypoints` | guidance_node | Planned path waypoints |
| `planning_actor-frontier` | guidance_node | Exploration frontiers |
| `planning_actor-room_segmentation` | guidance_node | Room boundaries |
| `dock_detector-dock_data` | perception_node | Charging dock detection |
| `stuck_detector-stuck_data` | perception_node | Stuck detection |
| `pcd_object_detection_actor-barrier_range_data` | perception_node | Point cloud obstacles |
| `dl_object_detection_actor-barrier_range_data` | perception_node | DL-detected obstacles |
| `dock_detector-barrier_range_data` | perception_node | Dock area obstacles |
| `point_cloud_preprocessor-filtered_sensor_data` | perception_node | Filtered 3D points |
| `semantic_map_actor-semantic_instances` | guidance_node | Semantic map objects |
| `cloud-cloud_stream_status_data` | cloud_node | Stream status |

### Control Sockets (REQ/REP pairs, TrifoIPC_ prefix)

Each node has:
- `TrifoIPC_{node}_REQ/REP` - General node control
- `TrifoIPC_{node}-mode_switch_REQ/REP` - Mode transitions

Notable control endpoints:
- `TrifoIPC_planning_actor-motion_command_*` - **Direct motor commands!**
- `TrifoIPC_sensor_node-robot_control_*` - **Robot hardware control**
- `TrifoIPC_txen_driver-robot_utility_command_*` - MCU utility commands
- `TrifoIPC_txen_driver-calibrate_data_to_bot_*` - Calibration data
- `TrifoIPC_cloud_actor-manual_controller_info_*` - Manual (joystick) control
- `TrifoIPC_cloud_actor-mapper_control_info_*` - Map control from cloud
- `TrifoIPC_slam_node-motion_detect_control_*` - Motion detection on/off
- `TrifoIPC_mapper-mapping_state_update_*` - Mapping state control
- `TrifoIPC_pcd_object_detection_actor-cloud_detection_params_*` - Detection tuning
- `TrifoIPC_planning_actor-cloud_planning_params_*` - Planning parameters
- `TrifoIPC_planning_actor-exception_control_info_*` - Error handling
- `TrifoIPC_planning_actor-planner_control_info_*` - Planner state control
- `TrifoIPC_planning_actor-stuck_control_info_*` - Stuck recovery control

---

## Key Config Files

| File | Content |
|------|---------|
| `/data/user/app/node_config/config_slam_node.json` | SLAM parameters, map_shader probabilities |
| `/data/user/app/node_config/config_guidance_node.json` | Navigation, cell sizes, cleaning params |
| `/data/user/app/node_config/config_camera_node.json` | Camera capture settings, encoder config |
| `/data/user/app/node_config/config_perception_node.json` | Object detection config |
| `/data/user/app/node_config/config_cloud_node.json` | Cloud/MQTT settings |
| `/data/user/app/rgbd_lua/trajectory_builder_2d.lua` | Cartographer SLAM tuning, layered_map_height_range |
| `/data/user/app/rgbd_lua/pose_graph.lua` | Loop closure, num_of_map_layer=3 |
| `/data/user/app/calib/calib_lucy.json` | Camera + sensor calibration |

---

## Implications for Local Control

1. **Live map access**: The mapper SHM can be read directly to get real-time occupancy grids without going through the cloud. A local tool could mmap `/dev/shm/TrifoSemaphore_mapper-multi_layer_map`, parse the protobuf layers, and render the map.

2. **Camera frames**: RGB and depth frames are available in SHM. An on-robot agent could read these for local video streaming (bypassing the cloud H.264 path).

3. **ZMQ control**: The `TrifoIPC_planning_actor-motion_command_*` and `TrifoIPC_sensor_node-robot_control_*` sockets provide a LOCAL path to direct motor control, without MQTT. This is the "Phase 3" ZMQ IPC control layer from `command_architecture.md`.

4. **Pose tracking**: `mapper-global_pose` ZMQ stream gives real-time robot position in map coordinates.

5. **OGM format SOLVED**: The SHM map uses the same protobuf format as the OGM files, with the grid encoding being raw uint8 probability values (scan_map layer). The "unknown" OGM encoding from `ogm_format_research.md` is simply the multi-layer protobuf with each layer having its own grid type.
