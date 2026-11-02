# Lucy ZMQ IPC Communication Topology

**Date:** 2026-03-27
**Source:** Live analysis of running Lucy robot (192.168.1.29)

## Overview

Lucy uses ZeroMQ (v4.3.0, built from source at `/home/perceptin/Downloads/zeromq-4.3.0/`) for all inter-process communication. The IPC layer is implemented in `libtrifo_core_port.so` with higher-level RPC in `libtrifo_core_rpc.so`. All Unix domain sockets live under `/data/local/tmp/`.

There are **two distinct communication patterns**:

1. **REQ/REP (Request/Reply)** via `TrifoIPC_*` sockets — command/control channels using DEALER/ROUTER socket types
2. **PUB/SUB (Publish/Subscribe)** via plain-named sockets — high-throughput data streaming

## Running Processes

| PID | Process | Role |
|-----|---------|------|
| 1247 | manager_node | Orchestrator, mode switching hub |
| 1278 | offline_node | Semantic mapping, offline processing |
| 1281 | slam_node | SLAM (Simultaneous Localization and Mapping) |
| 1282/11181 | calibrate_node | Camera/sensor calibration (2 instances) |
| 1283 | perception_node | Object detection, obstacle avoidance |
| 1284 | sensor_node | Hardware driver (MCU/STM32 via txen_driver) |
| 1285 | guidance_node | Path planning and motion control |
| 19534 | camera_node | Stereo camera input |
| 25697 | cloud_node | MQTT cloud bridge, remote control |

## Port Class Hierarchy (libtrifo_core_port.so)

```
trifo::port::Port (base)
├── trifo::port::ServerPort    — ZMQ REP socket, binds, handles Messages
├── trifo::port::ClientPort    — ZMQ REQ socket, connects, sends Messages
├── trifo::port::PubPort       — ZMQ PUB socket, publishes data streams
├── trifo::port::SubPort       — ZMQ SUB socket, subscribes to data streams
└── trifo::port::SensorDataPort — Specialized for sensor DataFrame items
```

Messages carry a `Header` + payload, and can contain `Command` or `Query` types.
Data is serialized via Protocol Buffers (`trifo::proto::ServiceMsg`).

## IPC Naming Convention

**REQ/REP channels:** `ipc:///data/local/tmp/TrifoIPC_{owner}-{channel_name}_{REQ|REP}`

Each channel creates a socket pair: `_REQ` (client connects) + `_REP` (server binds).

**PUB/SUB channels:** `ipc:///data/local/tmp/{owner}-{data_type}`

Single socket, publisher binds, subscribers connect.

---

## Channel Map: REQ/REP (Command/Control)

### Per-Node Service Channels
Every node has a base service channel and a mode_switch channel. manager_node sends mode_switch commands to all nodes to coordinate state transitions (idle, cleaning, docking, etc.)

| Socket Path | Owner (Server) | Purpose |
|-------------|----------------|---------|
| `TrifoIPC_manager_node_{REQ,REP}` | manager_node | Manager service endpoint |
| `TrifoIPC_manager_node-mode_switch_{REQ,REP}` | manager_node | **Mode switch broadcast hub** |
| `TrifoIPC_cloud_node_{REQ,REP}` | cloud_node | Cloud node service endpoint |
| `TrifoIPC_cloud_node-mode_switch_{REQ,REP}` | cloud_node | Mode switch for cloud node |
| `TrifoIPC_slam_node_{REQ,REP}` | slam_node | SLAM service endpoint |
| `TrifoIPC_slam_node-mode_switch_{REQ,REP}` | slam_node | Mode switch for SLAM |
| `TrifoIPC_guidance_node_{REQ,REP}` | guidance_node | Guidance/planning service |
| `TrifoIPC_guidance_node-mode_switch_{REQ,REP}` | guidance_node | Mode switch for guidance |
| `TrifoIPC_sensor_node_{REQ,REP}` | sensor_node | Sensor/MCU service endpoint |
| `TrifoIPC_sensor_node-mode_switch_{REQ,REP}` | sensor_node | Mode switch for sensor |
| `TrifoIPC_perception_node_{REQ,REP}` | perception_node | Perception service endpoint |
| `TrifoIPC_perception_node-mode_switch_{REQ,REP}` | perception_node | Mode switch for perception |
| `TrifoIPC_camera_node_{REQ,REP}` | camera_node | Camera service endpoint |
| `TrifoIPC_camera_node-mode_switch_{REQ,REP}` | camera_node | Mode switch for camera |
| `TrifoIPC_offline_node_{REQ,REP}` | offline_node | Offline processing service |
| `TrifoIPC_offline_node-mode_switch_{REQ,REP}` | offline_node | Mode switch for offline |
| `TrifoIPC_calibrate_node_{REQ,REP}` | calibrate_node | Calibration service |
| `TrifoIPC_calibrate_node-mode_switch_{REQ,REP}` | calibrate_node | Mode switch for calibration |

### Specialized REQ/REP Channels

| Socket Path | Connected Processes | Protobuf Type | Purpose |
|-------------|-------------------|---------------|---------|
| `TrifoIPC_sensor_node-robot_control_{REQ,REP}` | sensor_node (server) | `RobotControlCommandMsg` | **Direct motor/actuator control** |
| `TrifoIPC_planning_actor-motion_command_{REQ,REP}` | sensor_node (client) -> guidance_node (server) | `MotionCommandItemMsg` | Velocity commands to wheels |
| `TrifoIPC_planning_actor-planner_control_info_{REQ,REP}` | guidance_node (server) | `PlannerControlInfo` | Planner state/commands |
| `TrifoIPC_planning_actor-stuck_control_info_{REQ,REP}` | guidance_node (server) | Stuck detection control | Anti-stuck behavior |
| `TrifoIPC_planning_actor-exception_control_info_{REQ,REP}` | guidance_node (server) | Exception handling | Error recovery commands |
| `TrifoIPC_planning_actor-cloud_planning_params_{REQ,REP}` | guidance_node (server) | Planning parameters from cloud | Cloud-configurable planning |
| `TrifoIPC_planning_actor-mapper_control_info_{REQ,REP}` | slam_node (both client+server) | Mapper control | SLAM-planner coordination |
| `TrifoIPC_cloud_actor-mapper_control_info_{REQ,REP}` | slam_node (server) | Mapper control from cloud | Cloud map commands |
| `TrifoIPC_cloud_actor-manual_controller_info_{REQ,REP}` | cloud_node (server) | `ManualControllerInfoItemMsg` | **Joystick/manual remote control** |
| `TrifoIPC_cloud_actor-auto_test_data_{REQ,REP}` | cloud_node (server) | Auto-test data | Factory test interface |
| `TrifoIPC_cloud-cloud_stream_status_data_{REQ,REP}` | cloud_node (server) | `CloudStatusDataItemMsg` | Status data for cloud upload |
| `TrifoIPC_cloud-firmware_ota_data_from_bot_{REQ,REP}` | cloud_node (server) | Firmware OTA data | OTA update channel |
| `TrifoIPC_mapper-mapping_state_update_{REQ,REP}` | slam_node (server) | Mapping state | Map progress updates |
| `TrifoIPC_slam_node-motion_detect_control_{REQ,REP}` | perception_node (client) -> slam_node (server) | Motion detection | IMU/visual motion detection |
| `TrifoIPC_txen_driver-robot_utility_command_{REQ,REP}` | sensor_node (server) | `RobotUtilityCommandItemMsg` | **MCU utility commands** |
| `TrifoIPC_txen_driver-calibrate_data_to_bot_{REQ,REP}` | sensor_node (server) | `CalibrateDataItemMsg` | Calibration data to MCU |
| `TrifoIPC_lucy_camera_node-camera_control_info_{REQ,REP}` | camera_node (server) | `CameraControlCommandItemMsg` | Camera control commands |
| `TrifoIPC_pcd_object_detection_actor-cloud_detection_params_{REQ,REP}` | perception_node (server) | Detection params | Cloud-configurable detection |
| `TrifoIPC_semantic_map_actor-semantic_map_status_{REQ,REP}` | offline_node (server) | Semantic map status | Semantic mapping control |

## Channel Map: PUB/SUB (Data Streaming)

| Socket Path | Publisher | Subscribers | Data Type |
|-------------|-----------|-------------|-----------|
| `txen_driver-bot_data` | sensor_node | slam_node, guidance_node, perception_node | Wheel encoders, bumper, cliff sensors |
| `txen_driver-imu_data` | sensor_node | slam_node, calibrate_node | IMU (accelerometer/gyroscope) |
| `txen_driver-robot_status` | sensor_node | cloud_node, guidance_node | Robot status (battery, state, errors) |
| `txen_driver-audio_data` | sensor_node | cloud_node | Audio stream data |
| `bot-camera_sync` | sensor_node | camera_node | Timestamp sync between MCU and camera |
| `mapper-map_T_odom` | slam_node | guidance_node | Map-to-odometry transform |
| `mapper-global_pose` | slam_node | guidance_node, cloud_node | Global position estimate |
| `planning_actor-clean_status` | guidance_node | cloud_node, manager_node | Cleaning progress/status |
| `planning_actor-waypoints` | guidance_node | (visualization?) | Planned path waypoints |
| `planning_actor-room_segmentation` | guidance_node | cloud_node | Room boundary detection |
| `planning_actor-frontier` | guidance_node | (exploration) | Exploration frontiers |
| `cloud-cloud_stream_status_data` | cloud_node | (internal) | Aggregated status for cloud |
| `pcd_object_detection_actor-barrier_range_data` | perception_node | guidance_node | 3D obstacle ranges |
| `dl_object_detection_actor-barrier_range_data` | perception_node | guidance_node | Deep learning obstacle ranges |
| `dock_detector-barrier_range_data` | perception_node | guidance_node | Dock detection ranges |
| `dock_detector-dock_data` | perception_node | guidance_node | Dock position/state |
| `stuck_detector-stuck_data` | perception_node | guidance_node | Stuck detection events |
| `point_cloud_preprocessor-filtered_sensor_data` | perception_node | (internal actors) | Filtered 3D point cloud |
| `semantic_map_actor-semantic_instances` | offline_node | (internal) | Semantic object instances |

## TCP Endpoints

| Address | Library | Purpose |
|---------|---------|---------|
| `tcp://127.0.0.1:5555` | libtrifo_core_drivers.so, libtrifo_core_writers.so | Internal data writer/driver communication |
| `tcp://127.0.0.1:5678` | libtrifo_core_factory.so, libtrifo_core_wificfg.so | Factory test tool server |
| `tcp://*:%ld` | libtrifo_core_factory.so | Dynamic factory port binding |
| Port 5678 (tcp6) | com.trifo.netconfig (PID 944) | WiFi provisioning app (listening) |

## Data Flow Diagram

```
                    ┌─────────────────┐
                    │  MQTT Cloud     │
                    │  (our server)   │
                    └────────┬────────┘
                             │ TCP :17766
                    ┌────────┴────────┐
                    │   cloud_node    │ PID 25697
                    │                 │
                    │ cloud_actor-    │◄── manual_controller_info (joystick)
                    │   manual_ctrl   │◄── auto_test_data
                    │ cloud-firmware  │◄── OTA data
                    │ cloud-stream    │◄── status aggregation
                    │ cloud_actor-    │◄── mapper_control_info
                    │   mapper_ctrl   │
                    └──┬──────────┬───┘
                       │          │
          mode_switch  │          │ planning_actor-cloud_planning_params
                       ▼          ▼
              ┌────────────────────────────┐
              │       manager_node         │ PID 1247
              │  (mode switch orchestrator)│
              │                            │
              │  Sends mode_switch to ALL  │
              │  nodes via their           │
              │  mode_switch channels      │
              └────────────────────────────┘
                       │
          mode_switch to all nodes
                       │
    ┌──────────┬───────┴───────┬──────────┬──────────┐
    ▼          ▼               ▼          ▼          ▼
┌────────┐ ┌────────┐   ┌──────────┐ ┌────────┐ ┌────────┐
│sensor_ │ │slam_   │   │guidance_ │ │percep- │ │camera_ │
│node    │ │node    │   │node      │ │tion_   │ │node    │
│PID 1284│ │PID 1281│   │PID 1285  │ │node    │ │PID     │
│        │ │        │   │          │ │PID 1283│ │19534   │
└───┬────┘ └───┬────┘   └────┬─────┘ └───┬────┘ └───┬────┘
    │          │              │            │          │
    │ PUB:     │ PUB:         │ PUB:       │ PUB:     │
    │ bot_data │ map_T_odom   │ clean_     │ barrier_ │
    │ imu_data │ global_pose  │ status     │ range    │
    │ robot_   │              │ waypoints  │ dock_    │
    │ status   │              │ room_seg   │ data     │
    │ audio    │              │ frontier   │ stuck    │
    │          │              │            │          │
    │          │    REQ/REP:  │            │          │
    │◄─────────┼──── motion_  │            │          │
    │          │    command ──►│            │          │
    │          │              │            │          │
    │ REQ/REP: │              │            │          │
    │ robot_   │              │            │          │
    │ control  │              │            │          │
    │ robot_   │              │            │          │
    │ utility  │              │            │          │
    │ calibrate│              │            │          │
    │ _data    │              │            │          │
    └──────────┘              └────────────┘          │
         │                                            │
         │         txen_driver (STM32 MCU)            │
         └──────── Serial/USB to MCU ────────────────┘
                                                bot-camera_sync
```

## Key Findings for Local Control

### HIGH VALUE: Direct Robot Control Channels

1. **`TrifoIPC_sensor_node-robot_control`** — Direct motor control via `RobotControlCommandMsg`. This is how guidance_node tells the MCU to move wheels.

2. **`TrifoIPC_planning_actor-motion_command`** — Motion velocity commands (`MotionCommandItemMsg`). This is the interface between path planner and motor controller.

3. **`TrifoIPC_txen_driver-robot_utility_command`** — Utility commands to MCU (`RobotUtilityCommandItemMsg` containing `RobotControlCommandMsg`). Likely includes blower, side brush, main brush control.

4. **`TrifoIPC_cloud_actor-manual_controller_info`** — Manual/joystick control channel (`ManualControllerInfoItemMsg`). This is how the app does real-time directional control.

### Architecture Notes

- All REQ/REP channels use ZMQ DEALER/ROUTER socket types (not plain REQ/REP), enabling async request handling
- The `_REQ` suffix socket is the client side (DEALER), `_REP` is the server side (ROUTER)
- PUB/SUB channels use standard ZMQ PUB/SUB for one-to-many data distribution
- All messages are Protocol Buffer serialized (`trifo::proto::ServiceMsg` wrapper)
- manager_node has the MOST mode_switch connections (10+), confirming it's the orchestrator
- Each node re-creates socket pairs on reconnection (multiple inodes per path observed)

### Implications for On-Robot Agent

An on-robot ZMQ agent could:
1. **Subscribe** to PUB/SUB channels for real-time sensor data (pose, battery, obstacles)
2. **Send commands** via REQ/REP to `sensor_node-robot_control` for direct motor control
3. **Send commands** via `cloud_actor-manual_controller_info` to emulate joystick control
4. **Send mode_switch** commands to individual nodes to change operating mode
5. **Inject** motion commands via `planning_actor-motion_command` to control navigation

This would bypass the MQTT cloud protocol entirely and give full local control with sub-millisecond latency.
