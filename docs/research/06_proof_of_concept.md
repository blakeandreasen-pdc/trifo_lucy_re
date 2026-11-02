# Phase 6: Proof of Concept Scripts

## Overview

Three Python scripts have been created in `scripts/` to demonstrate protocol understanding and provide a foundation for building local Lucy control. These scripts document the protocols found in Phases 2–5.

**SAFETY RULES FOR ALL SCRIPTS**:
1. `lucy_decrypt.py` — safe to run anywhere (pure cryptography, no network)
2. `lucy_status.py` — read-only; safe to run on robot, but cannot affect operation
3. `lucy_mqtt_broker.py` — skeleton only; does NOT send commands by default (safe mode)

---

## 6.1 `lucy_decrypt.py` — Encryption Utility

**Location**: `scripts/lucy_decrypt.py`

### What it does

Implements all cryptographic functions found in Lucy's firmware binaries:

| Function | Source Binary | Algorithm | Used For |
|----------|---------------|-----------|---------|
| `qlcloud_encrypt` / `qlcloud_decrypt` | `libtrifo_core_cloud.so` | Rolling XOR (CREPT_1) | MQTT application-layer obfuscation |
| `iot_aes_cbc128_encrypt` / `iot_aes_cbc128_decrypt` | `libtrifo_core_cloud.so` | AES-128-CBC (CREPT_2) | MQTT alternative encryption |
| `trifo_crc16` | `libtrifo_robot.so` | CRC-16/CCITT (nibble) | Serial packet integrity |
| `build_trifo_packet` | `libtrifo_robot.so` | TrifoCommPayload framing | Serial packet construction |
| `verify_trifo_packet` | `libtrifo_robot.so` | Packet validation | Serial packet parsing |
| `ql_gen_product_sign` | `libtrifo_core_cloud.so` | MD5 | Cloud registration auth |
| `ql_gen_device_sign` | `libtrifo_core_cloud.so` | MD5 | Cloud session auth |

### How to use

```bash
# Run self-tests
python3 scripts/lucy_decrypt.py

# Import in your own code
from scripts.lucy_decrypt import qlcloud_decrypt, trifo_crc16, build_trifo_packet
```

### Example: Decrypt a captured MQTT payload

```python
from lucy_decrypt import qlcloud_decrypt

# Captured ciphertext (from Wireshark/tcpdump of live session)
ciphertext = bytearray.fromhex("a3f2b1...")

# initial_key and seed come from the QLCloud session establishment
# (not recoverable without capturing the handshake)
initial_key = 0x??
seed = 0x????????

plaintext = qlcloud_decrypt(ciphertext, 0, len(ciphertext), initial_key, seed)
print(plaintext.decode('utf-8', errors='replace'))
```

### Example: Verify a serial packet from /dev/ttyS3

```python
from lucy_decrypt import verify_trifo_packet, trifo_crc16

# Captured serial data (after AES-128-CTR decryption)
raw_packet = bytes.fromhex("74660104020000deadbeef????")
# (Last 2 bytes are CRC)

if verify_trifo_packet(raw_packet):
    group_id = raw_packet[2]
    payload_len = raw_packet[3]
    sub_id = raw_packet[4]
    payload = raw_packet[7:7+payload_len]
    print(f"Group: 0x{group_id:02X}, Sub: 0x{sub_id:02X}, Payload: {payload.hex()}")
```

### Limitations

- **Rolling XOR**: requires `initial_key` and `seed` from the live session (not statically recoverable)
- **AES-128-CTR** (serial): requires the AES key and IV (shared between RK3399 and STM32; embedded in firmware)
- **AES-128-CBC** (cloud): requires the session-negotiated key and IV

---

## 6.2 `lucy_status.py` — Status Reader

**Location**: `scripts/lucy_status.py`

### What it does

Connects to Lucy's internal ZeroMQ pub/sub bus and prints incoming messages from key status topics. This demonstrates how to read robot state from within the IPC layer.

**This script is completely read-only.** It subscribes to ZMQ topics but never publishes.

### Requirements

- Must run **on the robot** (the IPC sockets are UNIX domain sockets)
- Python 3 with pyzmq: `pip install pyzmq`

### How to use

```bash
# SSH to robot
ssh -oKexAlgorithms=+diffie-hellman-group1-sha1 -oHostKeyAlgorithms=+ssh-rsa \
    -oMACs=+hmac-sha1 -oPubkeyAcceptedAlgorithms=+ssh-rsa \
    -i ~/.ssh/trifo_lucy root@192.168.1.29

# On robot: install pyzmq if not present
pip install pyzmq --target=/tmp/pyzmq
export PYTHONPATH=/tmp/pyzmq

# Subscribe to all status topics
cd /data/user/app
python3 /tmp/lucy_status.py

# Or subscribe to a specific topic
python3 /tmp/lucy_status.py robot_status
python3 /tmp/lucy_status.py bot_data
python3 /tmp/lucy_status.py global_pose
```

### Subscribed Topics

| Topic Name | IPC Path | Content |
|-----------|----------|---------|
| `robot_status` | `txen_driver/robot_status` | Battery, charging state, error codes |
| `bot_data` | `txen_driver/bot_data` | Wheel odometry, cliff/bumper sensors |
| `imu_data` | `txen_driver/imu_data` | IMU accelerometer + gyroscope |
| `global_pose` | `mapper/global_pose` | Robot pose (x, y, theta) in map |
| `clean_status` | `planning_actor/clean_status` | Cleaning mode and state |
| `cloud_status` | `cloud/cloud_status_data` | Commands from cloud (mode switches) |

### Message Format

All messages are serialised `trifo::proto::ServiceMsg` Protocol Buffers. Without compiled `.proto` definitions, the script shows raw hex and any embedded ASCII strings.

To fully decode messages, compile the protobuf schema from Phase 2:

```protobuf
// Reconstruct from 02_message_protocol.md §2.1
message ServiceMsg {
  oneof data {
    SensorDataItemMsg         sensor_data_msg    = 1;
    CloudStatusDataItemMsg    cloud_status       = 2;
    // ... etc
  }
}
```

Then use:
```python
from google.protobuf import descriptor_pool, message_factory
# (requires compiled _pb2.py files from your .proto definitions)
```

### Expected Output

```
Connecting to 6 IPC topics...
  Subscribed: robot_status @ ipc:///data/local/tmp/txen_driver/robot_status
  Subscribed: bot_data @ ipc:///data/local/tmp/txen_driver/bot_data
  ...

Listening for messages (Ctrl+C to stop)...

[    0.12s] robot_status              #    1: [47 bytes] hex=0a2d0a2b0802...
[    0.25s] bot_data                  #    1: [82 bytes] hex=0a500a4e0801...
[    0.37s] global_pose               #    1: [28 bytes] hex=0a1a0a180801...
...
```

---

## 6.3 `lucy_mqtt_broker.py` — Local Cloud Skeleton

**Location**: `scripts/lucy_mqtt_broker.py`

### What it does

A skeleton local server that can replace the defunct Trifo cloud:

1. **HTTP dispatch server** (Flask): handles Lucy's registration request, returns your local MQTT broker address
2. **MQTT bridge** (paho-mqtt): connects to a local MQTT broker (e.g. Mosquitto), subscribes to all topics to observe Lucy's messages
3. **`LucyController`**: high-level command API (safe mode by default — no commands sent)

### Requirements

```bash
pip install flask paho-mqtt
# Plus a local MQTT broker:
apt install mosquitto  # Linux
brew install mosquitto  # macOS
```

### How to use

```bash
# 1. Start Mosquitto
mosquitto -p 1883 &

# 2. Start the local cloud skeleton (on your PC)
python3 scripts/lucy_mqtt_broker.py

# 3. Redirect DNS on Lucy
ssh root@192.168.1.29
echo '192.168.1.X  usdispatch.trifo.com' >> /etc/hosts
echo '192.168.1.X  usiot.trifo.com' >> /etc/hosts

# 4. Restart cloud_node on Lucy
kill $(cat /tmp/cloud_node.pid)  # or reboot
```

### Current Capabilities

| Feature | Status | Notes |
|---------|--------|-------|
| HTTP dispatch response | Implemented | Returns local MQTT broker address |
| Authentication acceptance | Implemented | Logs but accepts all connections |
| Product sign verification | Implemented | Optional MD5 check |
| Observe Lucy's MQTT messages | Implemented | Logs all topics and payloads |
| Parse known data point keys | Implemented | Updates `_robot_state` dict |
| Send commands | Skeleton | **Topic name unknown** — needs live capture |

### Key Gap: MQTT Topic Names

The biggest unknown for sending commands is the **MQTT topic name** that the QLCloud SDK uses. These topics are generated dynamically by the SDK from `product_id` and `dev_id`, and their format is not visible in the binary string table.

**To find the topic names**: Run Mosquitto with verbose logging while Lucy is connected (`mosquitto -v`). The output will show all topic subscriptions and publications, revealing the exact topic scheme.

Likely format based on QLCloud documentation patterns:
```
/{product_id}/{dev_id}/event      (device → cloud: data points)
/{product_id}/{dev_id}/cmd        (cloud → device: commands)
/{product_id}/{dev_id}/info       (device info)
```

### Extending to Full Control

Once the MQTT topics are known from live capture:

```python
# In lucy_mqtt_broker.py, update LucyController.send_command():
topic = f"/{PRODUCT_ID_US}/{dev_id}/cmd"

# Then enable commands (after thorough testing!):
controller = LucyController(bridge, safe=False)  # DANGER: disables safety mode
controller.start_clean(mode=1)  # starts cleaning
```

### Architecture Diagram

```
Your PC                          Lucy Robot
──────────────────────────       ──────────────────────
                                 cloud_node
                                     │
Mosquitto ◄──── MQTT ───────────────┤
   │       (port 1883)              │
   │                            (reads /etc/hosts)
   │                                │
Lucy Bridge ◄── reads topics        │ HTTP POST
   │                                ▼
Flask Dispatch ◄─────── HTTP ──► usdispatch.trifo.com
  (port 17766)                   (redirected to us)
   │
LucyController
   │
Your code here
```

---

## 6.4 Next Steps for Full Local Control

In priority order:

### 1. Capture Live MQTT Session (CRITICAL)
Connect Lucy to a Mosquitto broker on your LAN (using /etc/hosts redirect) and capture all MQTT traffic with `mosquitto -v` logging. This reveals:
- Exact topic names for commands
- Authentication packet format details
- Data point key→value encoding
- Heartbeat timing

### 2. Compile Protobuf Schemas
Reconstruct `.proto` files from the type names in Phase 2. Use `protoc` to compile, then import `*_pb2.py` in `lucy_status.py` to fully decode IPC messages.

### 3. Recover AES Serial Key
The AES-128-CTR key and IV for the serial link are the biggest remaining unknown. Options:
- Disassemble the `TBot` constructor in `libtrifo_robot.so` to find key derivation
- Attach gdbserver to `sensor_node` and read the key at runtime
- Monitor `/dev/ttyS3` output and brute-force if the key is derived from known values (serial number, MAC)

### 4. IPC-Native Control (Alternative Approach)
Instead of replacing the cloud, inject a process into Lucy's IPC bus:
- Run a Python script on Lucy via SSH
- Connect as a ZMQ publisher on `cloud/cloud_status_data`
- Publish `CloudStatusDataItemMsg` protobuf commands
- This bypasses the cloud entirely and directly controls the guidance_node
- Requires compiled protobuf definitions for `CloudStatusDataItemMsg`

---

## Cross-References

- See [Phase 2](02_message_protocol.md) for algorithm details implemented in `lucy_decrypt.py`
- See [Phase 3](03_zeromq_services.md) for the IPC topics used by `lucy_status.py`
- See [Phase 5](05_cloud_protocol.md) for the cloud protocol implemented in `lucy_mqtt_broker.py`
- See [Phase 4](04_mcu_protocol.md) for MCU serial packet format (in `build_trifo_packet`)
