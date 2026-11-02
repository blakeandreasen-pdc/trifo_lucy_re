# Phase 1: Process Architecture Map

## Overview

Lucy runs a custom robotics middleware stack on Linux (kernel 4.4.167, RK3399 SoC). All inter-process communication is done via **ZeroMQ over UNIX domain sockets** (IPC transport), with large data (camera frames, maps) passed via **shared memory with POSIX semaphores**. External TCP ports are only used for factory/calibration tooling.

The entire software stack lives in `/data/user/app/` and is launched by a single init service (`trifoapp`) that runs `run.sh`.

---

## Boot Sequence

### Init (`/system/etc/init/trifo.rc`)

On `sys.boot_completed=1`, Android init starts four services in parallel:

| Service | Command | Purpose |
|---------|---------|---------|
| `sys_config` | `./sys_config.sh` | Configure UART debug console and ADB via `/oem/.modectrl/.mode` |
| `trifoapp` | `./run.sh` | Main robot software stack (oneshot) |
| `check_reset` | `./check_reset.sh` | Factory reset button monitor (GPIO 102, polls every 0.5s) |
| `temp_ctrl` | `./temp_ctrl.sh` | Fan speed controller based on CPU temperature |
| `bootsound` | `tinyplay /system/media/audio/start.wav` | Startup chime |
| `sshd` | `dropbear -p 22` | SSH server (root password: `toor`) |

### `run.sh` Execution Sequence

1. **WiFi hostname**: Reads `/data/etc/trifo_config.json` for `wifi_name`, appends last 3 octets of wlan0 MAC → writes `wifi.cfg`, sets `net.hostname`
2. **OTA update check**: If `./app_update/` exists, MD5-verifies contents and copies over running app
3. **Log rotation**: Moves current log directory to `../log.backup/log.1`, keeps 50 backups, enforces 2 GB minimum free space
4. **Cleanup**: Removes `/dev/shm/*`, `/data/local/tmp/*`, clears SLAM logs
5. **Environment**: Sets `LD_LIBRARY_PATH=./lib`, `MALLOC_MMAP_THRESHOLD_=131072`
6. **Launch**: `taskset 33 ./bin/manager_node -config_file ./node_config/config_robot_node_manager.json`
   - `taskset 33` = CPU affinity mask 0x21 = CPUs 0 and 5 (A53 cores)
   - Stdout/stderr → `log/crash.log`

### `manager_node` Node Launch Sequence

`manager_node` reads `config_robot_node_manager.json` and spawns child processes. Serial MCU port is `/dev/ttyS3`. Launch order (all `node_launcher: true`):

| Node | Command | Priority |
|------|---------|---------|
| `sensor_node` | `taskset,c,nice,-n,-10,./bin/sensor_node,...` | nice -10, all CPUs |
| `cloud_node` | `./bin/cloud_node,...` | normal |
| `guidance_node` | `./bin/guidance_node,...` | normal |
| `slam_node` | `./bin/slam_node,...` | normal |
| `perception_node` | `./bin/perception_node,...` | normal |
| `camera_node` | `nice,-n,-5,./bin/camera_node,...` | nice -5 |
| `calibrate_node` | `./bin/calibrate_node,...` | normal |
| `offline_node` | `./bin/offline_node,...` | normal |
| `debug_node` | `./bin/debug_node,...` | nice +19, **disabled by default** |
| `log_play_node` | `./bin/log_play_node,...` | **disabled by default** |

---

## Running Processes (Observed Live)

```
manager_node    PID 1250   Parent supervisor, ZMQ coordinator
camera_node     PID 1284   RGBD camera capture (nice -5)
cloud_node      PID 1285   Cloud/MQTT communication
slam_node       PID 1286   SLAM / mapping
calibrate_node  PID 1287   Factory calibration + external TCP ports
sensor_node     PID 1289   MCU driver (STM32 via /dev/ttyS3)
guidance_node   PID 1290   Path planning / navigation
perception_node PID 1288   Obstacle detection, dock detection
offline_node    PID 1283   Semantic mapping (offline AI)

trifo.netconfig PID 947    Android APK — WiFi configuration (port 5678)
dropbear        PID 568    SSH server (port 22)
```

---

## Binary Inventory (`app/bin/`)

| Binary | Size | Role | Key Symbols |
|--------|------|------|-------------|
| `manager_node` | 157 KB | Supervisor; launches all child nodes; handles mode state machine (`CleanState`, `DockState`); monitors and restarts children | `NodeMonitor`, `RestartProgram`, `ModeSwitchCommand` |
| `sensor_node` | 166 KB | **MCU bridge**: reads sensor data from STM32 over `/dev/ttyS3`; publishes bot/IMU/status topics; drives motors/brushes/audio | `TxenDriver`, `SetCleanMotor`, `CloudStatusData`, audio |
| `camera_node` | 215 KB | Capture RGB (NV12 YUV, 1920×1080), depth (ToF point cloud), CG/CR IR; H.264 encoding; shared memory publish | `DataPublisherBase`, H264 encoder, `CameraControlCommand` |
| `cloud_node` | 129 KB | Cloud connectivity: QLCloud MQTT, stream server, WiFi config, OTA; bridges cloud commands to internal topics | `LucyCloudActor`, `LucyStreamServerActor`, `LucyWifiCfg` |
| `slam_node` | 80 KB | RGB-D SLAM using Cartographer (`pbstream` pose graph); publishes global pose, map, odometry | `LucyRgbdMapper`, pose graph, relocaliser |
| `guidance_node` | 68 KB | Path planning; zigzag, wall-follow, spiral, waypoint, docking, relocalisation modes | `LucyPlanningActor`, `StartClean`, `StartDock`, `StartAdvance` |
| `perception_node` | 92 KB | 3D obstacle detection (PCD + DL), dock IR detection, stuck detection, motion detection | `DockDetector`, `DLObjectDetectionActor`, `PcdObjectDetectionActor` |
| `offline_node` | 64 KB | Semantic mapping; runs TFLite segmentation + room classification offline | `SemanticMapActor`, TFLite models |
| `calibrate_node` | 56 KB | Factory calibration; binds external TCP ports 5556 and 7777; UDP multicast discovery | port 5556, 7777 |
| `debug_node` | 391 KB | Developer visualisation/debug (disabled in production); TCP agent port 12121 | `StartAgent` on port 12121 |
| `log_play_node` | 117 KB | Log playback for offline testing (disabled in production) | `StartLogPlay` |
| `factory_reset` | 105 KB | Factory reset utility; sends light/voice commands via `TBotAdapter` | `TBotAdapter`, CRC16 |
| `test_t_bot` | 101 KB | MCU test harness; direct `TBot` API | `TBot::SetDock`, `SetStop`, `SetCleanMotor` |

---

## Transport Layer Architecture

### Internal Communication (UNIX Domain Sockets via ZeroMQ)

All inter-process messaging uses **ZeroMQ 4.3.0** over UNIX domain sockets. Two patterns are used:

**1. Pub/Sub Data Topics** — files in `/data/local/tmp/`

The socket path IS the topic name. Publishers write, subscribers connect:

| Socket Path | Publisher | Subscribers | Data |
|-------------|-----------|-------------|------|
| `txen_driver-bot_data` | sensor_node | guidance_node, slam_node, perception_node, cloud_node | Wheel odometry, cliff/bumper sensors |
| `txen_driver-imu_data` | sensor_node | slam_node | IMU (accelerometer, gyro) |
| `txen_driver-robot_status` | sensor_node | cloud_node | Battery, error codes, charging state |
| `txen_driver-audio_data` | sensor_node | cloud_node, perception_node | Microphone audio |
| `mapper-global_pose` | slam_node | guidance_node, sensor_node | Robot pose (x, y, θ) in map frame |
| `mapper-map_T_odom` | slam_node | guidance_node | Map-to-odometry transform |
| `mapper-multi_layer_map` | slam_node | — | Full occupancy grid map |
| `visual_mapper-multi_layer_map` | slam_node | guidance_node, cloud_node | Visual map for cloud upload |
| `point_cloud_preprocessor-filtered_sensor_data` | perception_node | slam_node | Filtered LiDAR-like scan from ToF |
| `pcd_object_detection_actor-barrier_range_data` | perception_node | guidance_node, slam_node | 3D obstacle ranges |
| `dl_object_detection_actor-barrier_range_data` | perception_node | guidance_node, slam_node | AI obstacle ranges |
| `dock_detector-dock_data` | perception_node | guidance_node | Dock position |
| `dock_detector-barrier_range_data` | perception_node | guidance_node, slam_node | Dock area barriers |
| `stuck_detector-stuck_data` | perception_node | guidance_node, slam_node | Stuck detection signal |
| `planning_actor-clean_status` | guidance_node | cloud_node | Current cleaning state |
| `planning_actor-frontier` | guidance_node | debug_node | Exploration frontier |
| `planning_actor-room_segmentation` | guidance_node | cloud_node | Room segmentation data |
| `planning_actor-waypoints` | guidance_node | debug_node | Navigation waypoints |
| `semantic_map_actor-semantic_instances` | offline_node | cloud_node | Detected semantic objects |
| `cloud-cloud_stream_status_data` | cloud_node | — | Video stream status |
| `bot-camera_sync` | camera_node/sensor_node | slam_node | Camera-IMU time sync |

**2. RPC Request/Reply (TrifoIPC)** — named `TrifoIPC_{node}-{purpose}_REQ/REP`

Each node exposes REQ/REP sockets for receiving commands. Pattern: `manager_node` sends requests, child nodes reply.

Key RPC endpoints observed:

```
TrifoIPC_sensor_node-robot_control_REQ/REP      — Direct robot control commands
TrifoIPC_sensor_node-mode_switch_REQ/REP         — Mode state transitions
TrifoIPC_planning_actor-motion_command_REQ/REP   — Motion velocity commands
TrifoIPC_planning_actor-mapper_control_info_REQ/REP  — Map control (save/load)
TrifoIPC_cloud_actor-mapper_control_info_REQ/REP — Cloud-sourced map control
TrifoIPC_planning_actor-cloud_planning_params_REQ/REP — Cloud planning parameters
TrifoIPC_pcd_object_detection_actor-cloud_detection_params_REQ/REP — Cloud detection params
TrifoIPC_cloud-firmware_ota_data_from_bot_REQ/REP — OTA firmware from MCU
TrifoIPC_cloud_actor-manual_controller_info_REQ/REP — Manual drive commands from app
TrifoIPC_cloud-cloud_stream_status_data_REQ/REP — Video stream commands
TrifoIPC_txen_driver-robot_utility_command_REQ/REP — Utility commands to MCU
TrifoIPC_txen_driver-calibrate_data_to_bot_REQ/REP — Calibration data to MCU
TrifoIPC_mapper-mapping_state_update_REQ/REP     — SLAM state control
TrifoIPC_slam_node-motion_detect_control_REQ/REP — Motion detection enable/disable
TrifoIPC_lucy_camera_node-camera_control_info_REQ/REP — Camera parameter control
TrifoIPC_{node}_REQ/REP                          — Generic RPC per node (from manager)
TrifoIPC_{node}-mode_switch_REQ/REP              — Mode switch per node
```

**3. Shared Memory (Large Data)** — files in `/dev/shm/` with semaphores in `/data/local/tmp/`

Used for high-bandwidth data to avoid ZMQ copy overhead:

```
TrifoSemaphore_lucy_camera-image_data       — RGB frames (NV12, 1920×1080)
TrifoSemaphore_lucy_camera-depth_data       — Depth/point cloud frames
TrifoSemaphore_lucy_camera-cg_encode_data   — CG IR encoded data
TrifoSemaphore_lucy_camera-image_data_h264  — H.264 encoded video
TrifoSemaphore_mapper-multi_layer_map       — Full occupancy grid map
TrifoSemaphore_visual_mapper-multi_layer_map — Visual map
TrifoSemaphore_dl_object_detection_actor-percept_result_item — AI perception results
```

### External TCP Ports (ZeroMQ over TCP)

| Port | Protocol | Process | Purpose |
|------|----------|---------|---------|
| 5556 | ZeroMQ ZMTP 2.0 | `calibrate_node` | Factory calibration data port |
| 7777 | ZeroMQ ZMTP 2.0 | `calibrate_node` | REQ/REP — factory tool; echoes first byte |
| 5678 | ZeroMQ ZMTP 2.0 | `trifo.netconfig` (Android) | WiFi configuration; DEALER socket |
| 3888 | UDP multicast | `calibrate_node` | Device discovery: `239.0.1.1:3888` (sends `WhoIsTrifoV1`) |
| 22 | SSH | `dropbear` | Root shell access |

**Important correction to task document assumptions**: Port 5678 is bound by the Android netconfig APK (`com.trifo.netconfig`), not by the robot core stack. Ports 5556 and 7777 are calibration tooling only — they are **not** normal robot operation interfaces.

### RPC Transport (eProsima FastRTPS)

The `libtrifo_core_rpc.so` contains both ZeroMQ AND **eProsima FastRTPS** (DDS). The `ServiceManager` can route RPC over either transport. In practice, the live system uses ZMQ IPC. FastRTPS provides TCP/UDP DDS transport for potential remote tooling.

---

## Mode State Machine

The `manager_node` implements a mode state machine with signals sent to all child nodes:

```
States: CleanState, DockState, (idle)
Signal type: ModeSwitchCommand (contains StateSignalType set)
Transport: TrifoIPC_{node}-mode_switch_REQ/REP to each node
```

Key state signals observed: `kResumeClean` (guidance_node)

---

## Software Stack Summary Diagram

```
                        ┌─────────────────────────────────────┐
                        │           manager_node               │
                        │  (supervisor, mode state machine)    │
                        └──┬──────────┬──────────┬────────────┘
                           │ spawn    │ spawn    │ spawn ...
              ┌────────────▼─┐  ┌─────▼──────┐  ┌──────────────┐
              │ sensor_node  │  │ cloud_node │  │ camera_node  │
              │ /dev/ttyS3   │  │ QLCloud+   │  │ RGB+ToF+IR   │
              │ (STM32 MCU)  │  │ MQTT       │  │ H264 encode  │
              └──────┬───────┘  └──────┬─────┘  └──────┬───────┘
                     │                 │                │
         bot_data/   │    cloud cmds   │   image/depth  │ (shared mem)
         robot_status│                 │                │
                     │                 │                │
              ┌──────▼───────────────────────────────────▼──────┐
              │              ZeroMQ IPC Bus                       │
              │       (UNIX sockets in /data/local/tmp/)          │
              └──┬───────────────┬──────────────┬────────────────┘
                 │               │              │
        ┌────────▼───┐  ┌────────▼───┐  ┌──────▼────────┐
        │ slam_node  │  │guidance_   │  │ perception_   │
        │ Cartogr.   │  │node        │  │ node          │
        │ RGB-D SLAM │  │ path plan  │  │ PCD+DL+dock   │
        └────────────┘  └────────────┘  └───────────────┘
                                │ (optional)
                         ┌──────▼──────┐
                         │offline_node │
                         │ semantic AI │
                         └─────────────┘

External:
  App ──WiFi──► port 5678 (trifo.netconfig APK, ZMQ DEALER)
  Factory ────► port 5556/7777 (calibrate_node, ZMQ)
  Cloud ──────► QLCloud MQTT (cloud_node → usdispatch.trifo.com:17766)
  SSH ────────► port 22 (dropbear)
```

---

## Config File Locations

| File | Purpose |
|------|---------|
| `/data/etc/trifo_config.json` | Device configuration (wifi_name, serial_number, cloud_region) |
| `./node_config/config_*.json` | Per-node configuration |
| `./sysconfig.ini` | Fan control parameters |
| `./calib/calib_lucy.json` | Camera calibration (intrinsics/extrinsics) |
| `./rgbd_lua/` | Cartographer SLAM Lua configuration |
| `./wifi.cfg` | Current WiFi AP name (generated at boot) |
| `./data.db` | SQLite database (cleaning history, tasks, schedules) |
| `./bind_user_id` | Cloud-bound user ID |
| `./lucy_map/pose_graph_map.pbstream` | Saved Cartographer map |
| `./audio/config_voice_package.json` | Voice response configuration |

---

## DL Models in Use

| Model File | Framework | Purpose |
|-----------|-----------|---------|
| `./dl/18wrvh4p.tflite` | TFLite | 16-class obstacle segmentation (840×238 input) |
| `./dl/cpvus4ow.tflite` | TFLite | 18-class offline segmentation (640×360 input) |
| `./dl/tj2uzrc1_argmax.tflite` | TFLite | Room classifier (6 classes, 480×270 input) |
| Hardware accelerator: RK3399 NPU via `libmppapi.so` / `use_hardware_acc: true` |

---

*Confidence: High — confirmed from live process list, socket enumeration, config files, and binary symbols.*
