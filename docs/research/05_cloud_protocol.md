# Phase 5: Cloud Protocol Reconstruction

## Overview

Lucy's cloud communication uses the **QLCloud (QingLianYun / 清联云)** IoT SDK embedded in `libtrifo_core_cloud.so`. This is a Chinese IoT cloud platform SDK that implements:

1. **Device registration and authentication** via HTTP to a dispatch server
2. **MQTT** for ongoing device-cloud communication
3. **TLS** (mbedTLS) for transport security
4. **Application-layer encryption** (rolling XOR or AES-128-CBC, selectable)
5. **OTA firmware delivery** via chunked binary transfer over MQTT
6. **AWS S3** data upload for logs, maps, and sensor recordings

The cloud servers (`usdispatch.trifo.com`, `usiot.trifo.com`) are **defunct** as of Trifo's closure. This document reconstructs the full protocol to enable building a local replacement.

---

## 5.1 Region Configuration

Three regional deployments were supported:

| Region | Product ID | Product Key | Dispatch Server | Activate Server |
|--------|------------|-------------|-----------------|-----------------|
| US | 1009976843 | `a734264a61794bfc346463762762f429` | `usdispatch.trifo.com` | `usiot.trifo.com` |
| CN | 1008410591 | `6739f86528397651272364d36a6d43fe` | `cndispatch.triforobot.com` | `cniot.triforobot.com` |
| EU | 1009506721 | `376c3878d6666a48c628226b6453d923` | `eudispatch.trifo.com` | `euiot.trifo.com` |

**Shared port**: `activate_server_port: 17766` (non-standard; not 1883 or 8883)

**Region selection**: Set by `qly_type` in `config_cloud_node.json` (value: `"us"` for this device).

---

## 5.2 Authentication and Connection Flow

### Step 1: Product Sign Generation

Before any network contact, the device computes a `product_sign`:

```
product_sign = MD5(product_key + rand + mac)

where:
  product_key = "a734264a61794bfc346463762762f429" (US region)
  rand        = random 32-bit integer (new each session)
  mac         = wlan0 MAC address string (e.g., "aabbccddeeff")
```

**Function**: `ql_crypt_gen_product_sign()` in `libtrifo_core_cloud.so`

### Step 2: Device Registration (HTTP POST to dispatch server)

```http
POST http://usdispatch.trifo.com:17766/[registration_endpoint]
Content-Type: application/json

{
  "req": {
    "product_id": 1009976843
  },
  "data": {
    "product_sign": "<md5_hex_32chars>",
    "rand": <random_int>,
    "mac": "<wlan0_mac_address>",
    "pf": "<platform_hex>",
    "crypt_type": <0-9>,
    "sn": "<serial_number>"
  }
}
```

**Response** contains the MQTT broker address and a session token.

Functions used: `_parse_dispatch_ipinfo()`, `qlcloud_parse_dispatch_info()`, `qlcloud_get_dispatch_ipinfo()`, `qlcloud_open_dispatch_socket()`, `qlcloud_close_dispatch_socket()`

### Step 3: Device Authentication (MQTT CONNECT to dispatch broker)

After receiving broker details, the device authenticates:

```
device_sign = MD5(device_secret + rand + dev_id)

Authentication packet payload:
{
  "req": {
    "product_id": 1009976843
  },
  "data": {
    "product_sign": "<md5_hex>",
    "dev_sign": "<md5_hex>",
    "rand": <random_int>,
    "dev_id": "<device_id>",
    "mcu_version": "<fw_version_string>",
    "wifi_version": "<wifi_fw_version>",
    "rst": <reset_flag_int>,
    "unb": <unbind_flag_int>,
    "mcu": "<mcu_info>",
    "wifi": "<wifi_info>"
  }
}
```

**Functions**: `ql_crypt_gen_device_sign()`, `create_auth_pkt()`, `qlcloud_send_device_info()`, `qlcloud_logic_authed_handle()`

### Step 4: Ongoing MQTT Session

After authentication, the device:
- Publishes robot state as **data points** (dp_up)
- Receives commands from cloud as **downstream data points** (downdps)
- Maintains heartbeat via `qlcloud_process_heart()`
- Handles OTA via `qlcloud_process_otacmd()`, `qlcloud_process_otafileinfo()`, `qlcloud_process_otafilechunk()`

Persistence: `ql_persistence_data_save()` / `ql_persistence_data_load()` — saves auth tokens to disk so reconnection doesn't require full re-registration.

---

## 5.3 Application-Layer Encryption

All MQTT payload data is additionally encrypted at the application layer (on top of TLS). The `crypt_type` field in the registration packet selects the algorithm:

| Code | Algorithm |
|------|-----------|
| CREPT_0 | Plaintext (no encryption) |
| CREPT_1 | Custom rolling XOR (`encrypt_msg` / `decrypt_msg`) |
| CREPT_2 | AES-128-CBC (`iot_aes_cbc128_encrypt`) |
| CREPT_3 | SM4-ECB |
| CREPT_4 | SM4-CBC |
| CREPT_5–9 | Not confirmed; likely RSA wrapping or AES-256 variants |

See [Phase 2](02_message_protocol.md) §§2.4–2.6 for full implementation details and Python code for each cipher.

> **Speculation**: The robot likely negotiates CREPT_1 (rolling XOR) or CREPT_2 (AES-128-CBC) with the dispatch server. The actual value in use would be visible in a live MQTT session capture.

---

## 5.4 MQTT Data Points — Robot → Cloud (Upload)

The QLCloud SDK sends data using typed `dp_up_add_*` functions. These are the confirmed data point keys (extracted from `libtrifo_core_cloud.so` string table):

### Status and State

| Key | Type | Description |
|-----|------|-------------|
| `battery` | int | Battery level (0–100%) |
| `current_status` | enum | Current robot operational state |
| `clean_state` | enum | Cleaning state (idle/cleaning/paused/returning) |
| `clean_mode` | enum | Cleaning mode (auto/zigzag/wall-follow/spot/etc.) |
| `clean_time` | int | Cleaning session duration (seconds) |
| `clean_area` | float | Cleaned area (square meters) |
| `charger_pose` | binary | Charger position in map coordinates |
| `reloc_status` | enum | Relocalization status |
| `uptime` | int | System uptime (seconds) |
| `status_update_time` | int | Timestamp of last status update |
| `version` | string | Firmware version string |

### Map and Navigation

| Key | Type | Description |
|-----|------|-------------|
| `beauty_map` | binary | Rendered map image (PNG or similar) |
| `current_map_id` | int/string | Active map identifier |
| `lucy_map_version` | int | Map version number |
| `map_update_time` | int | Timestamp of last map update |
| `map_url` | string | URL for map upload/download (S3) |
| `upload_map` | bool/int | Trigger map upload |
| `map_manage_state` | enum | Map management state |
| `map_cell_size` | float | Map resolution (metres per cell; 0.025 m) |
| `map_max_point` | int | Maximum map grid points |
| `map_rotation_angle` | float | Map rotation angle |
| `map_file` | string | Map file path |

### Room Segmentation

| Key | Type | Description |
|-----|------|-------------|
| `room_id` | int | Room identifier |
| `room_name` | string | Room name (user-defined) |
| `room_type` | enum | Room type (bedroom, kitchen, etc.) |
| `room_type_id` | int | Room type numeric ID |
| `room_segmentation_info` | binary/JSON | Full room segmentation data |
| `room_segment_edited` | bool | Whether user has edited room boundaries |

### Semantic Mapping

| Key | Type | Description |
|-----|------|-------------|
| `semantic_instance_info` | binary/JSON | Detected furniture/object instances |

### Cleaning Statistics (Lifetime)

| Key | Type | Description |
|-----|------|-------------|
| `total_cleanups` | int | Total number of cleaning sessions |
| `total_time` | int | Total cleaning time (seconds) |
| `total_area` | float | Total cleaned area (m²) |
| `total_mainbrush` | int | Main brush runtime (hours or minutes) |
| `total_sidebrush` | int | Side brush runtime |
| `total_filter` | int | Filter runtime |

### Running Mode

| Key | Type | Description |
|-----|------|-------------|
| `running_mode_with_dock` | enum | Running mode when dock is present |
| `running_mode_without_dock` | enum | Running mode without dock |
| `running_without_dock` | bool | Currently running without dock |
| `running_dock` | bool | Currently docked/charging |

### Hardware Status

| Key | Type | Description |
|-----|------|-------------|
| `main_brush` | int | Main brush duty cycle or state |
| `side_brush` | int | Side brush duty cycle or state |
| `water_pump` | int | Mopping water pump state |
| `manual_blower` | int | Manual blower setting |
| `manual_blower_mode` | int | Manual blower mode |
| `manual_mopping_mode` | int | Manual mopping intensity mode |

### Diagnostic Logs

| Key | Type | Description |
|-----|------|-------------|
| `battery_log` | binary | Battery voltage/current log |
| `cliff_ir_log` | binary | Cliff sensor IR log |
| `bumper_ir_log` | binary | Bumper IR sensor log |
| `bumper_switch_log` | binary | Bumper mechanical switch log |
| `becaon_ir_log` | binary | Dock beacon IR signal log |

### Voice and Audio

| Key | Type | Description |
|-----|------|-------------|
| `voice_mode` | enum | Voice feedback mode |
| `voice_type` | int | Voice pack type |
| `voice_volume` | int | Speaker volume (0–100) |
| `voice_type_state` | enum | Voice type selection state |

### OTA Firmware

| Key | Type | Description |
|-----|------|-------------|
| `firmware_info_check` | string | Current firmware version for OTA check |
| `firmware_update` | bool | Firmware update in progress |
| `firmware_update_failed` | bool | Firmware update failed flag |
| `firmware_update_timeout` | bool | Firmware update timed out |
| `firmware_param_update` | bool | Firmware parameter update |
| `firmware_param_backup_failed` | bool | Param backup failed |
| `firmware_param_update_failed` | bool | Param update failed |
| `firmware_param_update_timeout` | bool | Param update timed out |
| `download_state` | enum | OTA download state |
| `download_succ_battery_low` | bool | Download succeeded but battery too low to install |

### Capability Flags (Feature Advertisement)

Sent during device info publication (`qlcloud_send_device_info`) to advertise supported features:

| Key | Value | Description |
|-----|-------|-------------|
| `support_donot_disturb_mode` | true | Do Not Disturb scheduling |
| `support_barrier_height` | true | Height-based barrier detection |
| `support_room_segmentation_robot` | true | Robot-side room segmentation |
| `support_semantic_instance_clean` | true | Clean specific semantic objects |
| `visable_wall_follow_switch` | true | Wall-follow mode visible in app |
| `visable_tirvs_switch` | true | TIRVS mode visible |
| `visable_low_area_enter_switch` | false | Low-area entry mode (hidden) |
| `support_max_blower_schedule_clean` | true | Max suction scheduling |
| `support_mopping` | true | Mopping supported |
| `support_all_info_json` | — | Support JSON full-info upload |
| `support_monitor_record_delete` | — | Support deleting surveillance recordings |
| `support_room_segmentation` | — | Room segmentation supported |
| `support_room_segmentation_by_robot` | — | Robot performs segmentation |
| `support_specific_area` | — | Specific area cleaning |
| `support_tool_log_record` | — | Tool data logging |
| `support_voice_package_download` | — | OTA voice packs |
| `support_volume_adjust` | — | Volume control |
| `tirvs_obstacle_avoid_distance_enable` | — | TIRVS obstacle distance control |

---

## 5.5 MQTT Data Points — Cloud → Robot (Download / Commands)

The cloud sends commands as **downstream data points** (`downdps`), processed by `qlcloud_process_downdps()`. The `cloud_node` then translates these into internal `CloudStatusDataItemMsg` protobuf messages on the `cloud/cloud_status_data` IPC topic.

### Cleaning Commands

| Key | Type | Description |
|-----|------|-------------|
| `running_mode_with_dock` | enum | Start cleaning with dock return mode |
| `running_mode_without_dock` | enum | Start cleaning without dock return |
| `running_without_dock` | bool | Run without returning to dock |
| `wait_restart_clean` | bool | Restart cleaning after waiting |
| `resume` | bool | Resume paused cleaning |
| `suspend` | bool | Pause cleaning |
| `countdown` | int | Countdown timer for scheduled clean |

### Navigation

| Key | Type | Description |
|-----|------|-------------|
| `wheel_speed` | float | Manual drive wheel speed (max 8.0 from config) |
| `charger_pose` | binary | Set charger position in map |

### Settings

| Key | Type | Description |
|-----|------|-------------|
| `donot_disturb_state` | bool | Enable/disable Do Not Disturb mode |
| `voice_type` | int | Select voice pack |
| `voice_volume` | int | Set volume |
| `water_pump` | int | Set mopping intensity |
| `enable_security` | bool | Enable surveillance/monitoring mode |
| `enable_map_manage` | bool | Enable map management |
| `low_space_cleaning_enable` | bool | Enable low-clearance area cleaning |
| `low_area_enter_enable` | bool | Allow entering low-clearance areas |
| `tirvs_obstacle_avoid_distance_enable` | bool | TIRVS distance control |

### Room Management (from app)

| Key | Type | Description |
|-----|------|-------------|
| `room_id` | int | Target room for operation |
| `room_name` | string | Set room name |
| `room_type` | enum | Set room type |
| `room_segment_edited` | bool | Room segmentation was edited |

### Map Operations

| Key | Type | Description |
|-----|------|-------------|
| `upload_map` | bool | Request map upload to cloud |
| `map_file` | string | Map file for upload/download |
| `enable_map_manage` | bool | Enable map management features |

### OTA Commands

| Key | Description |
|-----|-------------|
| `firmware_info_check` | Request firmware version check |
| `sys_info_check` | Request system info |
| `binfile_info_response` | Firmware file metadata |
| `binfile_chunk_response` | Firmware chunk data |
| `binfile_upgrade_response` | Upgrade result |
| `appdown_start_response` | App download start ACK |
| `compels_upgrade_response` | Forced upgrade response |

---

## 5.6 OTA Update Flow

Lucy supports two OTA mechanisms:

### 5.6.1 QLCloud OTA (MCU Firmware)

The QLCloud SDK handles MCU firmware updates via its own chunked protocol:

```
Cloud → Robot:
  1. qlcloud_process_otacmd()     — cloud initiates OTA
  2. qlcloud_process_otafileinfo() — file size, CRC, version
  3. qlcloud_process_otafilechunk() — binary chunks (check_binfile_chunk)
  4. qlcloud_process_ota_appdown() — app download
  5. qlcloud_process_ota_compels() — compelled/forced upgrade
  6. qlcloud_process_otapassive()  — passive OTA (robot-initiated check)

Robot → Cloud:
  cloud_request_ota_check()      — robot requests OTA check
  create_ota_check_pkt():
  {
    "req": {"token": "<session_token>"},
    "data": {
      "upgradetype": <int>,
      "product_id": <int>,
      "version": "<current_version>",
      "bin": <binary_flag>,
      "owner": <owner_id>,
      "chunksize": <chunk_size>
    }
  }
```

Firmware file path on robot: `calib/trifo_robot_platform.bin`
OTA staging path: `/data/user/ota/app/calib/trifo_robot_platform.bin`

### 5.6.2 Application OTA (Robot Software Stack)

A separate mechanism using a custom server:

```
deploy_ota_remote_server: "https://windmillyu.top"
deploy_ota_protocol_version: "1.3"
```

Downloaded to `/data/user/ota/`, then copied over the running app by `run.sh` on next boot (MD5-verified before applying).

---

## 5.7 Video Streaming

Lucy supports live video streaming to a CDN. The `cloud_node` config shows two CDN providers:

### Tencent Cloud CDN (active)

```
cloud_type: "tencent"

Pull domain:  lt.lightfieldcamera.com.cn
Pull key:     F34tG54U
Push domain:  pt.lightfieldcamera.com.cn
Push key:     RT56hyt4tgfTYGvdd57tfbAD6MN9fh4e
Stream name:  [derived from device ID]
App name:     app-name
Expired time: 36000 seconds (10 hours per token)
RTSP port:    8554 (for local RTSP, disabled: enable_rtsp: false)
```

### Aliyun CDN (backup)

```
Pull domain:  live.lightfieldcamera.com.cn
Pull key:     PrulyzNWF5
Push domain:  push.lightfieldcamera.com.cn
Push key:     l5aSvKxqsJ
```

### Stream Content

| Topic | Content | Format |
|-------|---------|--------|
| `lucy_camera/image_data_h264` | RGB camera | H.264, 20 fps, 1920×1080 |
| `lucy_camera/cg_encode_data` | CG IR camera | Encoded, 10 fps |
| `txen_driver/audio_data` | Microphone | PCM, 2ch, 44100 Hz, 16-bit |

Audio processing: Speex noise suppression enabled (`speex_noise_suppress: -35 dB`)

---

## 5.8 AWS S3 Data Upload

`cloud_node` can upload sensor data, map files, and diagnostic logs to AWS S3:

```
Region:  ap-east-1 (Hong Kong)
Bucket:  dl-data-collect/
Path:    /lucy_record_data/

SDK: libaws-cpp-sdk-s3.so, libaws-cpp-sdk-core.so
```

Access credentials (from `config_cloud_node.json`, values removed from this copy):
```
access_keyid: <redacted>
secret_key:   <redacted>
```

> **Note**: These credentials may be invalidated. They were embedded in the config file visible on the device. A commented-out set of alternative credentials is also present in the config.

---

## 5.9 Device Binding and User Account

The robot binds to a user account via the cloud. Binding state is persisted on disk:

| Function | Description |
|---------|-------------|
| `cloud_bind_state_get/set` | Get/set binding state (bound/unbound) |
| `cloud_bind_time_get` | Get binding timestamp |
| `cloud_bind_timeout_get` | Get binding timeout |
| `cloud_unbound_state_get/set` | Get/set unbinding state |
| `cloud_rst_state_get/set` | Get/set reset state |
| `qlcloud_process_bindinfo` | Handle bind/unbind commands from cloud |

The `./bind_user_id` file (in `/data/user/app/`) stores the bound user ID.

Factory reset (triggered by GPIO 102 button hold, 10 seconds) calls `factory_reset` binary which clears binding state.

---

## 5.10 Building a Local Cloud Replacement

To replace the defunct Trifo cloud with a local server, implement the following:

### Minimal Replacement Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Lucy Robot                         │
│                                                      │
│  cloud_node ──MQTT──► [Your local broker]            │
│                                ▲                     │
│  (modify /etc/hosts or DNS     │                     │
│   to redirect trifo.com        │                     │
│   to your server)              │                     │
└────────────────────────────────┼────────────────────┘
                                 │
┌────────────────────────────────┼────────────────────┐
│              Your Local Server │                     │
│                                                      │
│  1. HTTP dispatch server       │ → serves dispatch   │
│     (usdispatch.trifo.com:17766)  info (broker IP)  │
│                                                      │
│  2. MQTT broker (Mosquitto)    │ → port 17766        │
│     - accepts robot auth                             │
│     - forwards data points to your app               │
│     - sends commands as downstream data points       │
│                                                      │
│  3. Your control app           │ → reads status,     │
│     (lucy_mqtt_broker.py)         sends commands     │
└─────────────────────────────────────────────────────┘
```

### Step-by-Step

1. **Redirect DNS**: On Lucy, add to `/etc/hosts`:
   ```
   192.168.x.x  usdispatch.trifo.com
   192.168.x.x  usiot.trifo.com
   ```
   Or configure your router's DNS to redirect `*.trifo.com` to your server.

2. **HTTP dispatch endpoint**: Respond to the registration POST with:
   ```json
   {
     "res": {"code": 0},
     "data": {
       "ip": "192.168.x.x",
       "port": 17766,
       "token": "your_generated_token"
     }
   }
   ```

3. **MQTT broker**: Accept connections with the credentials from the auth packet. The `dev_sign` can be verified or simply accepted. Use MQTT QoS 0 or 1.

4. **Command topic structure**: The QLCloud SDK uses an internal topic scheme (not standard MQTT topic names visible to us). Commands travel as JSON payloads on SDK-managed topics. The `downdps` handler in the SDK translates these to data point callbacks.

   > **Key challenge**: The exact MQTT topic names used by QLCloud internally are not in the string table. They are likely generated dynamically from the `product_id` and `dev_id`. Wiresharking a live session (before Trifo shutdown) would have revealed these. Topic format guess: `/{product_id}/{dev_id}/cmd` and `/{product_id}/{dev_id}/data`.

5. **Authentication bypass**: Since the cloud is dead, the simplest approach may be to patch `cloud_node` (or use `LD_PRELOAD`) to skip signature verification. Alternatively, compute the correct signatures from the known product key.

6. **`activate_enabled: false`**: This field in `config_cloud_node.json` is already `false`, suggesting the activation step may already be skipped in this firmware version.

---

## 5.11 Internal IPC → Cloud Translation

When `cloud_node` receives an MQTT downstream command, it translates it to an internal protobuf:

```
MQTT downdps (JSON key-value)
    ↓ qlcloud_dp_handle()
CloudStatusDataItemMsg protobuf (populated from JSON values)
    ↓ ZMQ pub on cloud/cloud_status_data
guidance_node → executes the command
```

**CloudStatusDataItemMsg** fields (confirmed from `CloudStatusDataFrame` class in `libtrifo_core_cloud.so`):
- `CloudModeSwitchData` — mode transitions (clean, dock, stop, pause, resume)
- Other CloudDataType entries for map commands, settings changes, manual control

**CloudDataType enum** is used as the key in `CloudStatusDataFrame::At<T>(CloudDataType)` template.

---

## 5.12 Full Communication Stack Summary

```
┌─────────────────────────────────────────────────────┐
│                    Cloud Stack                       │
├────────────┬────────────────────────────────────────┤
│ Layer      │ Technology                             │
├────────────┼────────────────────────────────────────┤
│ Transport  │ TCP/IP over WiFi (RTL8822BS)           │
│ TLS        │ mbedTLS (server cert: QLCloud CA)      │
│ Protocol   │ MQTT over TLS, port 17766              │
│ Auth       │ MD5 product_sign + dev_sign            │
│ Encryption │ QLCloud rolling XOR or AES-128-CBC     │
│ Format     │ JSON data points (dp_up/downdps)       │
│ OTA        │ Chunked binary over MQTT               │
│ Video      │ RTMP push → Tencent/Aliyun CDN         │
│ Data       │ AWS S3 (ap-east-1) for logs/maps       │
└────────────┴────────────────────────────────────────┘
```

---

## Cross-References

- See [Phase 2](02_message_protocol.md) for encryption algorithms (rolling XOR, AES-CBC, SM4)
- See [Phase 3](03_zeromq_services.md) for how cloud commands become IPC messages
- See [Phase 6](06_proof_of_concept.md) for the `lucy_mqtt_broker.py` skeleton implementation
- See [scripts/lucy_mqtt_broker.py](../scripts/lucy_mqtt_broker.py) for the local broker skeleton
