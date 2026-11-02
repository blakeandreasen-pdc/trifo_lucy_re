# Phase 4: STM32 MCU Communication Protocol

## Overview

The RK3399 Linux SoC communicates with the STM32F407 MCU over a UART serial link at `/dev/ttyS3`. The MCU handles all low-level hardware: drive motors, cleaning motors (main brush, side brush, blower), cliff/bumper sensors, wheel encoders, IMU, LEDs, audio/speaker, and battery monitoring.

The protocol stack is:

```
Application (TBot C++ API)
    ↓
TrifoProtocolParser::Encode() — packet framing
    ↓
TBot::encrypt() — AES-128-CTR encryption
    ↓
Serial::Write() — /dev/ttyS3 UART
    ↓ (physical wire)
STM32F407 — decrypts, decodes, executes
```

All implementation is in `libtrifo_robot.so`, source at:
`/home/jenkins/agent/TrifoRobotics/bot/base/modules/robot/`

---

## 4.1 UART Serial Configuration

| Parameter | Value |
|-----------|-------|
| Device | `/dev/ttyS3` |
| Baud rate | Unknown — set by `Serial::set_speed(fd, speed)` using `cfsetispeed`/`cfsetospeed` |
| Data format | 8N1 (standard embedded serial) |
| Flow control | None (inferred) |
| Direction | Full duplex |

> **Note**: The baud rate value is set at runtime and was not found as a literal string in the binary. Common embedded MCU rates are 115200, 460800, or 921600. Likely 115200 based on the STM32F407's typical UART configurations, but this requires runtime confirmation.

---

## 4.2 Packet Format (`TrifoProtocolParser`)

**Source file**: `trifo_protocol_parser.cpp`

Every packet has a fixed header followed by a variable-length payload and a 2-byte CRC:

```
Offset  Len  Field         Description
------  ---  -----         -----------
0       2    Magic         0x74, 0x66 — ASCII 'tf' (Trifo signature)
2       1    Group ID      MessageGroupID enum (see 4.3)
3       1    Payload len   N (number of payload bytes)
4       1    Sub-ID        Sub-group or command sub-type
5       1    Flags[0]      Control/flags byte
6       1    Flags[1]      Control/flags byte
7       N    Payload       Command or sensor data bytes
7+N     2    CRC16         Big-endian CRC-16/CCITT over bytes [0..6+N]
```

Total packet length: **9 + N bytes**

> **Confirmed**: Magic bytes `0x74 0x66` ('tf') stored little-endian as 16-bit halfword `0x6674` at packet start. AES-128-CTR encryption is applied over the entire packet before transmission.

### C++ struct (inferred)

```cpp
struct TrifoCommPayload {
    enum MessageGroupID : uint8_t {
        kGroupPose     = ??,  // Position/odometry data
        kGroupSensor   = ??,  // Sensor (IMU, cliff, bumper, battery)
        kGroupFirmware = ??,  // Firmware upgrade commands
        // ... additional groups
    };

    uint8_t  group_id;
    uint8_t  payload_length;
    uint8_t  sub_id;
    uint8_t  flags[2];
    uint8_t  payload[255];  // variable

    uint8_t  GetPayloadLength() const;
};
```

Confirmed message groups from binary strings:
- `Group POSE` — position/odometry related
- `Group SENSOR` — sensor data
- `Group Firmware` — firmware upgrade protocol

---

## 4.3 CRC-16 Algorithm

**Function**: `crc16(buf, len, initial_crc)` in `libtrifo_robot.so` at offset 0x198824

A nibble-based CRC-16/CCITT implementation (Kermit variant, polynomial 0x1021):

```python
# Standard CRC-16/CCITT (Kermit) table — reflected polynomial 0x8408
CRC16_TABLE = [
    0x0000, 0x1189, 0x2312, 0x329B, 0x4624, 0x57AD, 0x6536, 0x74BF,
    0x8C48, 0x9DC1, 0xAF5A, 0xBED3, 0xCA6C, 0xDBE5, 0xE97E, 0xF8F7
]

def crc16(data: bytes, initial: int = 0xFFFF) -> int:
    """CRC-16/CCITT nibble-based — matches TrifoProtocolParser implementation."""
    crc = initial & 0xFFFF
    for byte in data:
        nibble_lo = (byte ^ crc) & 0x0F
        crc = CRC16_TABLE[nibble_lo] ^ (crc >> 4)
        nibble_hi = ((byte >> 4) ^ crc) & 0x0F
        crc = CRC16_TABLE[nibble_hi] ^ (crc >> 4)
    return crc & 0xFFFF
```

CRC is computed over bytes `[0 .. 6+N]` (the full packet excluding the 2-byte CRC field itself), then appended big-endian.

---

## 4.4 AES-128-CTR Encryption Layer

**Function**: `trifo::robot::TBot::encrypt(out, in_len, key, iv, in)` at `libtrifo_robot.so` offset 0x46198

Every packet is AES-128-CTR encrypted before transmission. This uses OpenSSL EVP:

```c
// Encryption (same function used for decryption — CTR mode is symmetric)
EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
EVP_EncryptInit_ex(ctx, EVP_aes_128_ctr(), NULL, key_16bytes, iv_16bytes);
EVP_EncryptUpdate(ctx, out, &out_len, in, in_len);
EVP_EncryptFinal_ex(ctx, out + out_len, &final_len);
EVP_CIPHER_CTX_free(ctx);
// returns: out_len + final_len
```

Decryption uses the same CTR keystream: `EVP_DecryptInit_ex` / `EVP_DecryptUpdate` / `EVP_DecryptFinal_ex`.

**Key and IV sources**: The 16-byte key and 16-byte IV are not statically determinable from the binary. They likely derive from one of:
- The device serial number stored in `/data/etc/trifo_config.json`
- The firmware platform file `calib/trifo_robot_platform.bin`
- The firmware parameter files `calib/latest_firmware_params.bin` / `calib/origin_firmware_params.bin`
- A hardcoded constant in the STM32 firmware

> **Speculation**: The firmware platform binary (`trifo_robot_platform.bin`, the MCU firmware itself) likely contains the shared secret. Both sides (RK3399 and STM32) must have the same key at init time. The key derivation function is embedded in `libtrifo_robot.so` but requires disassembly of the `TBot` constructor to extract.

---

## 4.5 TBot C++ API — Available Commands

The `trifo::robot::TBot` class exposes the following methods. These are the complete set of operations available to control the MCU:

### Motion Control

| Method | Signature | Description |
|--------|-----------|-------------|
| `SetMove` | `TBot::SetMove(MoveDirection dir, float speed, float angular_vel, float distance, uint8_t flags)` | Move robot — sets wheel speeds for direction, speed, turn rate, and optional distance |
| `SetStop` | `TBot::SetStop(uint8_t flags)` | Stop all motion immediately |
| `SetDock` | `TBot::SetDock(uint8_t flags)` | Initiate/cancel docking to charging station |
| `SetWallFollow` | `TBot::SetWallFollow(MoveDirection dir, float speed, uint8_t flags)` | Wall-following mode |

**`MoveDirection` enum values** (inferred from usage):
- Forward, Backward, Left, Right, RotateCW, RotateCCW (exact names unconfirmed)

### Cleaning Hardware Control

| Method | Signature | Description |
|--------|-----------|-------------|
| `SetCleanMotor` | `TBot::SetCleanMotor(TbotCleanMotorId motor_id, int8_t duty_cycle)` | Set cleaning motor speed (-127 to +127) |
| `SetCarpetBoostControl` | `TBot::SetCarpetBoostControl(uint8_t enable)` | Enable/disable carpet boost mode (increases suction on carpet) |

**`TbotCleanMotorId` enum** (from `RobotCleanMotorCommand::MotorID`):

| ID | Motor | Config Values |
|----|-------|---------------|
| Main brush | Main rolling brush | dock=20, clean=50 (duty cycle %) |
| Side brush | Side sweeping brush | dock=30, clean=40 (dock low power=15) |
| Blower | Suction fan | min=25, max=78, max_pet=88 (mode values) |

`RobotCleanMotorCommand` fields: `motor_id()`, `duty_cycle()`, `duty_period()`

**`GetSafetyDutyCycle(int, int, int8_t, int8_t)`** — safety limiter applied to duty cycle values before sending.

### Status Queries

| Method | Description |
|--------|-------------|
| `TBot::GetFirmwareVersion()` | Request MCU firmware version string |
| `TBot::GetMotorState(TbotCleanMotorId, uint8_t)` | Query current motor state |
| `TBot::QueryIMUHeating()` | Query IMU heater status |

### Peripheral Control

| Method | Signature | Description |
|--------|-----------|-------------|
| `SetLight` | `TBot::SetLight(LightData const&)` | Control LEDs (ring light, status light) |
| `SetIMUHeating` | `TBot::SetIMUHeating(bool enable)` | Control IMU heater (for thermal stability) |
| `SetRobotAdminStatus` | `TBot::SetRobotAdminStatus(TbotAdminStatus const&)` | Set administrative/operational status |

**`LightData` struct**: Used for LED control — specific fields unknown, but controls the robot's status LED ring.

### IMU Subsystem

```
IMU commands (sent as string commands to MCU):
  IMU_RESET             — reset IMU
  IMU_HEATER_SWITCH_ON  — enable IMU heater
  IMU_HEATER_SWITCH_OFF — disable IMU heater
```

**Callback registration**: `TBot::RegisterIMUSensorDataCallback(function<void(BotIMUSensor const&)>)` — registers a callback for incoming IMU data from MCU.

### Firmware Upgrade

| Method | Description |
|--------|-------------|
| `TBot::UpgradeFirmware(string const& path)` | Begin MCU firmware upgrade from file path |
| `TBot::WriteFirmwareConfigCmd(MessageGroupID, uint8_t sub_id, const uint8_t* data, int len, bool)` | Low-level firmware config write |
| `TBot::ProcessFirmwareUpgradeResponse(TrifoCommPayload const&)` | Handle firmware upgrade ACK/response from MCU |

Firmware file: `calib/trifo_robot_platform.bin` (version 2.28.0 at time of analysis)

---

## 4.6 Sensor Data from MCU

The MCU sends sensor data back to the RK3399. This arrives as `TrifoCommPayload` packets which are decoded by the `TBot` state machine:

### `BotDataSensor` — Polling Sensor Frame

Published as `txen_driver/bot_data` IPC topic by `sensor_node`.

**Contents** (inferred from config and symbol analysis):

| Field | Description |
|-------|-------------|
| Wheel encoder L | Left wheel tick count / velocity |
| Wheel encoder R | Right wheel tick count / velocity |
| Cliff sensors | Array of cliff IR sensor readings (threshold: 4 triggers) |
| Bumper sensors | Bumper switch states (front, sides) |
| IMU (accelerometer) | X, Y, Z accelerometer (embedded in BotDataSensor or separate) |
| IMU (gyroscope) | X, Y, Z gyro |
| Wall IR sensor | Side wall IR distance |
| Charging contact | Dock charging state |

**Confirmed sensor config** (from `config_sensor_node.json`):
```
cliff_ir_triggered_threshold: 4   (4+ readings → cliff detected)
robot_move_pose_threshold: 0.003  (3mm position threshold)
robot_move_angle_threshold: 0.02  (0.02 rad ≈ 1.1° angle threshold)
```

### `RobotStatusDataFrame` — Status Summary

Published as `txen_driver/robot_status` IPC topic.

Contains a `map<DataType, shared_ptr<RobotStatusData>>` keyed by `DataType` enum. Confirmed types:
- Battery level/voltage
- Charging state (`GetChargeState`)
- Error/fault codes
- Motor states

**`ZBot::GetChargeState()`** and **`WBot::GetRobotStatus()`** variants exist for different MCU hardware generations. Lucy uses `TBot`.

### `BotIMUSensor` — IMU-Specific Data

Published as `txen_driver/imu_data` IPC topic (separate from bot_data for SLAM latency reasons).

---

## 4.7 `RobotUtilityCommand` — Utility Commands

The `txen_driver/robot_utility_command` IPC topic carries `RobotUtilityCommandItemMsg` protobuf messages. The `command_type` field (confirmed via `RobotUtilityCommand::command_type()`) selects the operation.

Utility commands include: light control, audio/voice playback, blower mode changes, and other miscellaneous hardware operations that don't fit the main motion/sensor loop.

---

## 4.8 Data Flow Diagram

```
           /dev/ttyS3 (UART)
           ┌─────────────────────────────────┐
           │       STM32F407 MCU              │
           │  Motors: drive, brush, blower    │
           │  Sensors: cliff, bumper, encoder │
           │  IMU: accel + gyro              │
           │  Battery monitor                 │
           │  LED ring, speaker               │
           └──────────┬──────────────────────┘
                      │ AES-128-CTR encrypted
                      │ TrifoCommPayload packets
                      │ (magic 0x74 0x66, CRC-16)
                      ▼
           ┌─────────────────────────────────┐
           │        libtrifo_robot.so         │
           │  TBot class:                     │
           │    - Serial::Read/Write          │
           │    - TBot::encrypt/decrypt       │
           │    - TrifoProtocolParser         │
           │    - CircleBuffer (ring buffer)  │
           │    - AnalysisPackage()           │
           └──────────┬──────────────────────┘
                      │ C++ callbacks
                      ▼
           ┌─────────────────────────────────┐
           │          sensor_node             │
           │  TxenDriver actor:               │
           │    - RegisterSensorCallback      │
           │    - RegisterRobotStatusCallback │
           │    - RegisterIMUSensorCallback   │
           └──────────┬──────────────────────┘
                      │ ZMQ IPC Pub/Sub
                      ▼
         ┌────────────────────────────────────┐
         │ txen_driver/bot_data               │ → guidance_node, slam_node, perception_node
         │ txen_driver/imu_data               │ → slam_node
         │ txen_driver/robot_status           │ → cloud_node
         │ txen_driver/robot_utility_command  │ (subscribed by sensor_node from guidance)
         └────────────────────────────────────┘
```

---

## 4.9 Other Bot Implementations (Non-Lucy)

`libtrifo_robot.so` contains implementations for multiple robot hardware generations:

| Class | Robot | Notable Differences |
|-------|-------|---------------------|
| `TBot` | Lucy (this robot) | Full feature set; AES-CTR serial |
| `WBot` | Older platform | `SetBlowerMode`, `SetLightStatus`, `GetVirtualWallState`, `SetVirtualWallEnableMode` |
| `YBot` | Another variant | `SetBlowerMode`, `SetLightStatus`, `GetRobotStatus` |
| `ZBot` | Another variant | `SetCleaner`, `SetBrushStatus`, `SetLight`, `GetChargeState` |
| `HBot` | Another variant | `SetMoveDist`, `SetMoveMode`, `SetMoveSquare` (distance-based motion API) |

All share the same `TrifoProtocolParser` packet format and `Serial` layer. Differences are in the higher-level command semantics.

---

## 4.10 Key Unknowns

| Unknown | Notes |
|---------|-------|
| AES key/IV values | Must be extracted from MCU firmware or by runtime tracing |
| Exact baud rate | Not found as literal; likely 115200 or 460800 |
| `MessageGroupID` enum values | Names confirmed (POSE, SENSOR, Firmware); numeric values not recovered |
| Sub-ID encoding per group | Each group has its own sub-command table, not recovered |
| `DataType` enum values for `RobotStatusDataFrame` | Names not recovered |
| Complete `BotDataSensor` struct layout | Field offsets not recovered |
| `TbotCleanMotorId` enum values | Main brush, side brush, blower confirmed; numeric values not recovered |

---

## Cross-References

- See [Phase 2](02_message_protocol.md) §2.8 for the serial packet format and AES-128-CTR details
- See [Phase 1](01_process_architecture.md) for `sensor_node` role in the overall architecture
- See [Phase 3](03_zeromq_services.md) for the IPC topics (`txen_driver/*`) that carry MCU data
- See [scripts/lucy_decrypt.py](../scripts/lucy_decrypt.py) for Python implementations of the crypto layers
