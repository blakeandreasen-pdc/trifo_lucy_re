# Phase 2: Message Protocol Analysis

## Overview

Lucy uses **two entirely separate protocol stacks**:

1. **Internal IPC** — ZeroMQ UNIX domain sockets carrying **Protocol Buffers (protobuf)**
2. **Cloud communication** — MQTT over TLS, carrying JSON packets encrypted with the **QLCloud IoT SDK**

The MCU serial link (`/dev/ttyS3`) has its own binary packet format with AES-128-CTR encryption.

---

## 2.1 Internal IPC Message Format (ZeroMQ + Protobuf)

### Transport Layer

All internal process-to-process messages travel over ZeroMQ on UNIX domain socket paths under `/data/local/tmp/`. There are two patterns:

| Pattern | Socket Type | Use Case |
|---------|------------|----------|
| Publish / Subscribe | PUB/SUB | Continuous data streams (sensor frames, map updates, status) |
| Request / Reply | REQ/REP (via `ServiceManager`) | One-shot commands, RPC-style calls |

### Message Container

Every IPC message is a serialized `ServiceMsg` Protocol Buffer. `ServiceMsg` contains a `oneof data` field — only one message type is populated per envelope.

**Reconstructed `ServiceMsg` proto schema** (inferred from symbol analysis):

```protobuf
// Namespace: trifo::proto
message ServiceMsg {
  oneof data {
    SensorDataItemMsg            sensor_data_msg             = 1;
    CloudStatusDataItemMsg       cloud_status                = 2;
    CameraCalibInfoItemMsg       camera_calib_info           = 3;
    CameraControlCommandItemMsg  camera_control_info         = 4;
    ManualControlInfoItemMsg     manual_control_info         = 5;
    ManualControllerInfoItemMsg  manual_controller_info      = 6;
    MapperControlInfoItemMsg     mapper_control_info         = 7;
    MotionCommandItemMsg         motion_command              = 8;
    MultiLayerGridMapItemMsg     multilayer_grid_map         = 9;
    ListOfMultiLayerGridMapItemMsg list_of_multilayer_grid_map = 10;
    PlanningLayerItemMsg         planning_layer              = 11;
    Pose2DItemMsg                reloc_result                = 12;
    RobotUtilityCommandItemMsg   robot_utility_command       = 13;
    SystemModeMsg                system_mode                 = 14;
    SystemStatusMsg              system_status               = 15;
    CommandStatusMsg             command_status              = 16;
    CalibrateDataItemMsg         calibrate_data              = 17;
    InvalidMsg                   test_msg                    = 18;
  }
}
```

> **Note**: Field numbers are inferred — actual numbers may differ. The type names are confirmed from C++ mangled symbol names in the binaries.

### RPC Wrapper Messages

For REQ/REP calls, `ServiceMsg` is wrapped in one of:

```protobuf
message RPCRequestBase {
  trifo.proto.RequestType      type        = 1;
  trifo.proto.RequestAttribute attribute   = 2;
  uint32                       session_id  = 3;
  uint32                       seq         = 4;
  // plus a serialized ServiceMsg payload
}

message RPCReplyBase {
  trifo.proto.ReplyAttribute   attribute   = 1;
  uint32                       session_id  = 2;
  // plus a serialized ServiceMsg payload
}
```

These are defined in `libtrifo_core_rpc.so` and used by all nodes.

### Additional Pub/Sub Message Types

Used on dedicated ZMQ pub/sub topics (confirmed from `debug_node` symbols):

| Proto Type | Content |
|-----------|---------|
| `MapItemMsg` | Occupancy map data |
| `PathItemMsg` | Navigation path |
| `Pose2DItemMsg` | 2D pose (x, y, theta) |
| `BarrierItemMsg` | Obstacle/barrier range |
| `FrontierItemMsg` | Frontier exploration points |
| `SensorDataItemMsg` | Full sensor frame (IMU, wheel odometry, ToF, etc.) |
| `RobotStatusDataItemMsg` | Robot status summary |
| `MultiLayerGridMapItemMsg` | Multi-layer grid map (navigation + semantic) |
| `ModeSwitchCommandItemMsg` | Mode switch signal |
| `StateTypeItemMsg` | Current robot state |
| `SystemModeMsg` | Mode message with `.signal` (ModeSwitchCommandItemMsg) and `.state` (StateTypeItemMsg) |
| `SystemStatusMsg` | System status with current operational state |
| `CloudStatusDataItemMsg` | Cloud → robot command frame |
| `RobotUtilityCommandItemMsg` | Utility commands (light, voice, calibrate) |
| `CameraCalibInfoItemMsg` | Camera calibration info |
| `CameraControlCommandItemMsg` | Camera control commands |

### Wire Encoding

Protobuf messages are serialized to bytes using the standard protobuf binary encoding (`SerializeWithCachedSizes` / `MergePartialFromCodedStream`). No additional framing beyond ZeroMQ's built-in message framing.

For large binary data (camera frames, maps), messages carry only metadata; actual pixel/map data is exchanged via **shared memory** (`/dev/shm/`). The IPC message acts as a notification/metadata envelope only.

---

## 2.2 Alternative Transport: eProsima FastRTPS (DDS)

`libtrifo_core_rpc.so` also embeds **eProsima FastRTPS** (Data Distribution Service). This appears to be a second transport option for pub/sub traffic — potentially for higher-bandwidth or reliability scenarios.

The `RPCPublisher` and `RPCSubscriber` classes in `libtrifo_core_rpc.so` wrap both ZeroMQ and FastRTPS:

- `RPCPublisher::init(topic_name, qos)` → creates a FastRTPS publisher
- `RPCPublisher::Publish(bytes)` → publishes serialized payload
- `RPCSubscriber::init(topic_name, callback, ...)` → creates a FastRTPS subscriber

The serialized payload format is the same protobuf bytes wrapped in eProsima's CDR (Common Data Representation):

```cpp
// Serialization (CdrSerializedSize used for sizing)
_ZN5trifo3rpc20GetCdrSerializedSizeENSt6__ndk16vectorIhNS1_9allocatorIhEEEEi
_ZN5trifo3rpc11RPCDataType9serializeEPvPN8eprosima8fastrtps4rtps19SerializedPayload_tE
_ZN5trifo3rpc11RPCDataType11deserializeEPN8eprosima8fastrtps4rtps19SerializedPayload_tEPv
```

In practice, the robot appears to use ZeroMQ IPC for all inter-node communication (confirmed from live socket enumeration in Phase 1). FastRTPS may be for future use or external tooling.

### ZeroMQ CurveZMQ (libsodium)

`libtrifo_core_rpc.so` includes **libsodium** (NaCl) primitives:

| Function | Algorithm |
|---------|-----------|
| `crypto_box` | Curve25519 + XSalsa20 + Poly1305 |
| `crypto_secretbox` | XSalsa20 + Poly1305 (symmetric) |
| `crypto_sign` | Ed25519 signatures |
| `crypto_scalarmult` | Curve25519 DH |
| `crypto_hash` | SHA-512 |

These are present for **ZeroMQ CURVE security** — ZMQ's built-in authenticated encryption for the transport. However, the live system appears to use ZMQ without CURVE (the IPC sockets use UNIX domain paths, where CURVE is less commonly applied). *This needs runtime confirmation.*

---

## 2.3 QLCloud IoT Message Format (MQTT Cloud Protocol)

Cloud messages go through the **QLCloud / QingLianYun (清联云)** SDK embedded in `libtrifo_core_cloud.so`. The SDK implements its own protocol over TCP/MQTT.

### Authentication and Registration Flow

The QLCloud protocol uses JSON packets. Key packet formats extracted from binary strings:

**Registration packet** (device → dispatch server, HTTP):
```json
{
  "req": {"product_id": <int>},
  "data": {
    "product_sign": "<md5_hex>",
    "rand": <random_int>,
    "mac": "<mac_address>",
    "pf": "<platform_hex>",
    "crypt_type": <encrypt_type_int>,
    "sn": "<serial_number>"
  }
}
```

**Authentication packet** (device → MQTT broker, after registration):
```json
{
  "req": {"product_id": <int>},
  "data": {
    "product_sign": "<md5_hex>",
    "dev_sign": "<md5_hex>",
    "rand": <random_int>,
    "dev_id": "<device_id>",
    "mcu_version": "<fw_version>",
    "wifi_version": "<wifi_fw_version>",
    "rst": <reset_flag>,
    "unb": <unbind_flag>,
    "mcu": "<mcu_info>",
    "wifi": "<wifi_info>"
  }
}
```

**Data upload packet**:
```json
{
  "req": {"token": "<session_token>"},
  "data": <data_payload>
}
```

**OTA check request**:
```json
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

### Signing Functions

| Function | Purpose |
|---------|---------|
| `ql_crypt_gen_product_sign` | Generate `product_sign` = MD5(product_key + rand + mac) |
| `ql_crypt_gen_device_sign` | Generate `dev_sign` = MD5(device_secret + rand + dev_id) |
| `iot_encode_md5` | MD5 → hex string |
| `iot_encode_base64` | Base64 encode |
| `iot_decode_base64` | Base64 decode |

### Encrypt Type Selection (`crypt_type` field)

The `crypt_type` field in registration packets is set by `ql_client_get_encrypt_type()` which reads a global variable set during SDK init. The binaries contain strings `CREPT_0` through `CREPT_9` identifying 10 encryption type codes:

| Code | Likely Algorithm |
|------|----------------|
| CREPT_0 | No encryption (plaintext) — confirmed by `encrypt_msg` being trivially callable |
| CREPT_1 | Custom rolling XOR (encrypt_msg/decrypt_msg) |
| CREPT_2 | AES-128-CBC (iot_aes_cbc128_encrypt) |
| CREPT_3 | SM4-ECB |
| CREPT_4 | SM4-CBC |
| CREPT_5–9 | RSA, AES-256, or combinations (speculative) |

> **Note**: The specific CREPT code → algorithm mapping is inferred. The actual mapping requires runtime tracing. CREPT_1 (rolling XOR) is the most likely code negotiated with the dead cloud, as it's the simplest and the function is exported alongside the CREPT strings.

### Data Point Upload Functions

The QLCloud SDK provides typed data point upload functions:

```c
dp_up_add_int(handle, key, value)
dp_up_add_string(handle, key, value)
dp_up_add_float(handle, key, value)
dp_up_add_bool(handle, key, value)
dp_up_add_enum(handle, key, value)
dp_up_add_fault(handle, key, value)
dp_up_add_binary(handle, key, value, len)
```

These build the `data` payload for upload packets (the data points map to MQTT-reported robot properties).

---

## 2.4 Custom Rolling XOR Cipher (`encrypt_msg` / `decrypt_msg`)

**Location**: `libtrifo_core_cloud.so` at offsets 0x1989e0 (encrypt) and 0x198954 (decrypt)

This is the QLCloud SDK's custom message obfuscation cipher. It is **not strong cryptography** — it provides basic traffic obfuscation but not meaningful security.

### Algorithm

The cipher is a **rolling XOR with a linear congruential key schedule**.

```
Parameters:
  buf          : uint8_t*  — buffer, modified in-place
  start        : uint16_t  — first byte index to process
  end          : uint16_t  — one-past-last byte index
  initial_key  : uint8_t   — starting key byte
  seed         : uint32_t  — key schedule seed
```

**Key schedule setup** (from seed):
```
step_hi = signed_mod1024(seed >> 10) + 371   # 0x173
step_lo = signed_mod1024(seed)       + 829   # 0x33d

where signed_mod1024(x) = ((x & 0x3ff) - (x >> 31 >> 22 & 0x3ff))
                          (signed modulo for negative values)
```

**Encrypt loop** (i from start to end-1):
```
key_input   = buf[i] ^ key                     # XOR byte with key
buf[i]      = key_input                        # store ciphertext in-place
key         = ((key_input + key) * step_hi     # linear congruential step
               + step_lo) & 0xfff + 0x6f      # mod 4096, then +111
```

**Decrypt loop** (identical structure, inverse key schedule order):
```
ciphertext  = buf[i]
key_input   = ciphertext + key                 # same expression as encrypt
buf[i]      = ciphertext ^ key                 # XOR recovers plaintext
key         = (key_input * step_hi + step_lo) & 0xfff + 0x6f
```

**The two functions are symmetric** (XOR is its own inverse, and the key schedule uses the *same* value — the ciphertext byte plus old key — in both directions). Calling either function twice with the same parameters returns the original data.

### Python Implementation

```python
def _signed_mod(x: int, mod: int) -> int:
    """Signed modulo (handles negative values like the AArch64 ASR trick)."""
    r = x % mod
    return r

def _setup_steps(seed: int) -> tuple:
    """Compute step_hi and step_lo from seed."""
    seed = seed & 0xFFFFFFFF
    # signed_mod1024 of (seed >> 10)
    hi_raw = (seed >> 10) & 0x3FF
    lo_raw = seed & 0x3FF
    step_hi = hi_raw + 0x173   # +371
    step_lo = lo_raw + 0x33D   # +829
    return step_hi, step_lo

def _next_key(key_input: int, step_hi: int, step_lo: int) -> int:
    """Advance the key one step."""
    t = (key_input * step_hi + step_lo) & 0xFFF
    return (t + 0x6F) & 0xFF  # +111, keep as byte

def encrypt_msg(buf: bytearray, start: int, end: int,
                initial_key: int, seed: int) -> bytearray:
    """
    QLCloud custom rolling XOR cipher — encrypt.
    Modifies buf[start:end] in-place (symmetric, so also decrypts).
    """
    step_hi, step_lo = _setup_steps(seed)
    key = initial_key & 0xFF
    for i in range(start, end):
        ciphertext = (buf[i] ^ key) & 0xFF
        key_input  = (ciphertext + key) & 0xFFFFFFFF
        buf[i]     = ciphertext
        key        = _next_key(key_input, step_hi, step_lo)
    return buf

def decrypt_msg(buf: bytearray, start: int, end: int,
                initial_key: int, seed: int) -> bytearray:
    """
    QLCloud custom rolling XOR cipher — decrypt.
    Functionally equivalent to encrypt_msg (symmetric XOR cipher).
    """
    step_hi, step_lo = _setup_steps(seed)
    key = initial_key & 0xFF
    for i in range(start, end):
        ciphertext = buf[i]
        key_input  = (ciphertext + key) & 0xFFFFFFFF
        buf[i]     = (ciphertext ^ key) & 0xFF
        key        = _next_key(key_input, step_hi, step_lo)
    return buf
```

> **Usage note**: The `initial_key` and `seed` values are set by the QLCloud SDK during connection setup. Without capturing a live session, their exact runtime values are unknown. They likely derive from `rand` (the random nonce in the registration packet) and the product key.

---

## 2.5 AES-128-CBC (`iot_aes_cbc128_encrypt` / `iot_aes_cbc128_decrypt`)

**Location**: `libtrifo_core_cloud.so` at 0x1a0c3c (encrypt, 176 bytes) and 0x1a0950 (decrypt, 748 bytes)

Standard AES-128-CBC from the QLCloud SDK's own AES implementation (not OpenSSL — separate from mbedTLS).

**Encrypt function** (pseudo-signature):
```c
int iot_aes_cbc128_encrypt(
    const uint8_t *in,
    int           in_len,
    const uint8_t *key,
    int           *key_len_ptr,  // pointer to key length (must be 16)
    uint8_t       *iv            // 16-byte IV, also passed as mode table ptr
) -> 0 on success, -1 on error
```

**Decrypt** performs full CBC chaining with **PKCS7 unpadding**:
- After decryption, reads last byte `p = buf[out_len - 1]`
- If `p <= 0x10`: subtracts `p` from output length (removes padding)
- If `p > 0x10`: treats as no padding (non-standard, possibly a quirk)

**Python equivalent**:
```python
from Crypto.Cipher import AES

def iot_aes_cbc128_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    # PKCS7 pad to 16-byte boundary
    pad_len = 16 - (len(plaintext) % 16)
    plaintext += bytes([pad_len] * pad_len)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(plaintext)

def iot_aes_cbc128_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = cipher.decrypt(ciphertext)
    # PKCS7 unpad (only if last byte <= 0x10)
    pad = plaintext[-1]
    if pad <= 0x10:
        plaintext = plaintext[:-pad]
    return plaintext
```

---

## 2.6 SM4 (Chinese National Cipher)

**Location**: `libtrifo_core_cloud.so`

| Function | Offset | Size |
|---------|--------|------|
| `ql_sm4_setkey_enc` | 0x19b7e8 | 12 |
| `ql_sm4_setkey_dec` | 0x19b7f4 | 324 |
| `ql_sm4_encrypt_ecb` | 0x19b950 | 620 |
| `ql_sm4_decrypt_ecb` | 0x19bbbc | 500 |
| `ql_sm4_encrypt_cbc` | 0x19bdc0 | 1148 |
| `ql_sm4_decrypt_cbc` | 0x19c23c | 276 |

SM4 is a Chinese national standard symmetric block cipher (128-bit block, 128-bit key). Functionally equivalent to AES in security level. Used as an alternative to AES when `crypt_type` selects it.

---

## 2.7 mbedTLS (Cloud TLS)

The MQTT connection to the QLCloud dispatch server uses **mbedTLS** for TLS. The following mbedTLS components are present in `libtrifo_core_cloud.so`:

| Component | Functions Present |
|-----------|-----------------|
| RSA | `mbedtls_rsa_rsaes_pkcs1_v15_encrypt/decrypt`, `mbedtls_rsa_pkcs1_*` |
| AES | `mbedtls_internal_aes_encrypt/decrypt`, `mbedtls_aes_crypt_ecb` |
| GCM | `mbedtls_gcm_crypt_and_tag`, `mbedtls_gcm_auth_decrypt` |
| PKI | `mbedtls_pk_encrypt/decrypt`, `mbedtls_pk_parse_subpubkey` |
| SSL/TLS | `mbedtls_ssl_*` (full TLS client stack) |
| X.509 | `mbedtls_x509_get_name` |
| ECDH | `mbedtls_ecdh_make_params` |
| Ciphers | `mbedtls_cipher_crypt`, `mbedtls_cipher_auth_encrypt/decrypt` |

This is used for the MQTT broker TLS connection. The root CA certificate for QLCloud's dispatch server would be embedded or loaded from disk.

---

## 2.8 RK3399 ↔ STM32 Serial Protocol (`TrifoProtocolParser`)

**Location**: `libtrifo_robot.so`

### Packet Format

The serial protocol between the RK3399 (Linux) and STM32F407 (MCU) uses a fixed binary packet format assembled by `TrifoProtocolParser::Encode`:

```
Offset  Len  Description
------  ---  -----------
0       2    Magic: 0x7466 ('tf' big-endian)  — bytes 0x74, 0x66
2       1    Message type/category
3       1    Payload length (N bytes)
4       1    Flags/control byte
5       1    Flags byte 2
6       1    Flags byte 3
7       N    Payload data (N = byte[3] value)
7+N     2    CRC16 checksum (big-endian)

Total packet length: 9 + N bytes
```

> **Confirmed**: Magic `0x6674` stored as a 16-bit halfword at [x19] by `strh w8, [x19]` with `w8 = 0x6674`. Since AArch64 is little-endian, this stores bytes `0x74 0x66` ('tf') at offsets 0, 1.

### CRC16

**Function**: `crc16(buf, len, initial_crc)` at offset 0x198824

The CRC uses a **nibble-based lookup table** (16 entries × 2 bytes) at data section offset 0x390. The algorithm processes 2 nibbles per byte:

```python
TABLE = None  # 16 uint16 entries, loaded from binary at runtime

def crc16(data: bytes, initial: int = 0xFFFF) -> int:
    """CRC-16/CCITT nibble-based implementation."""
    crc = initial & 0xFFFF
    for byte in data:
        nibble_lo = (byte ^ crc) & 0x0F
        crc = TABLE[nibble_lo] ^ (crc >> 4)
        nibble_hi = ((byte >> 4) ^ crc) & 0x0F
        crc = TABLE[nibble_hi] ^ (crc >> 4)
    return crc & 0xFFFF
```

The polynomial is CRC-16/CCITT (0x1021) with initial value 0xFFFF — standard for embedded serial protocols. CRC is computed over bytes [0 .. 7+N-1] (everything before the CRC field).

### AES-128-CTR Encryption Layer

The serial data is encrypted using AES-128-CTR before transmission:

**Function**: `trifo::robot::TBot::encrypt(out, in_len, key, iv, in)` at 0x46198

```
Uses OpenSSL EVP API:
  EVP_CIPHER_CTX_new()
  EVP_aes_128_ctr()         ← confirmed by BL to EVP_aes_128_ctr offset
  EVP_EncryptInit_ex(ctx, cipher, NULL, key, iv)
  EVP_EncryptUpdate(ctx, out, &out_len, in, in_len)
  EVP_EncryptFinal_ex(ctx, out + out_len, &final_len)
  EVP_CIPHER_CTX_free(ctx)
  returns: out_len + final_len
```

The corresponding decrypt uses `EVP_DecryptInit_ex`, `EVP_DecryptUpdate`, `EVP_DecryptFinal_ex`.

**Key and IV sources**: Not statically determinable. Runtime values. Likely derived from the device serial number, hardware ID, or a shared secret in the MCU firmware (`calib/trifo_robot_platform.bin`).

### Full Serial Data Flow

```
RK3399 → MCU:
  1. Build CommPayload struct (type, length, flags, payload bytes)
  2. TrifoProtocolParser::Encode → raw packet bytes
  3. TBot::encrypt(raw_packet) → encrypted_bytes
  4. Serial::Write(encrypted_bytes) → /dev/ttyS3

MCU → RK3399:
  1. Serial::Read from /dev/ttyS3 → encrypted_bytes
  2. TBot::decrypt(encrypted_bytes) → raw_bytes
  3. TrifoProtocolParser::Push(raw_bytes) → feeds state machine
  4. TrifoProtocolParser::DecoderStateMachine → assembled CommPayload
  5. TrifoProtocolParser::VerifyTrifoPacket → CRC check
  6. Callback with validated CommPayload
```

---

## 2.9 Cloud Utility Functions

Additional utility functions in `libtrifo_core_cloud.so`:

| Function | Description |
|---------|-------------|
| `STREAM_TO_UINT16_f` | Parse big-endian uint16 from byte stream |
| `STREAM_TO_UINT32_f` | Parse big-endian uint32 from byte stream |
| `UINT32_TO_STREAM_f` | Write big-endian uint32 to byte stream |
| `UINT16_TO_STREAM_f` | Write big-endian uint16 to byte stream |
| `STREAM_TO_FLOAT32_f` | Parse big-endian float32 |
| `FLOAT32_TO_STREAM_f` | Write big-endian float32 |
| `mac_up_3` | Read 3 bytes → 24-bit big-endian integer (for MAC address handling) |
| `hex2char` | Hex character ('0'-'9', 'a'-'f', 'A'-'F') → nibble value |
| `tolower_convert` | ASCII to lowercase |
| `v_strncpy` | Bounded string copy |
| `str2int` | String to integer |
| `str2float` | String to float |
| `QL_MD5Init/Update/Final` | MD5 implementation |
| `iot_encode_md5` | MD5 and encode as hex string |

---

## 2.10 APK Protocol (Trifo Home App)

The APK decompilation was not performed in this phase (jadx not installed). However, from the binary analysis:

- **Port 5678** is bound by the Android app component `com.trifo.netconfig` (PID 947), **not** the robot core stack
- The app communicates with the robot using ZeroMQ DEALER/ROUTER (port 5678) for configuration tasks (WiFi setup, provisioning)
- The app likely uses the same protobuf message format (ServiceMsg) and possibly the same rolling XOR cipher

**Known app-side endpoints from node config**:
- Port 5678: ZeroMQ, DEALER socket type, accepts WiFi configuration commands
- Port 7777: ZeroMQ REQ/REP, used by calibration tool (`calibrate_node`)

---

## 2.11 Summary: Encryption Layer Map

```
┌─────────────────────────────────────────────────────────────┐
│                    Lucy Encryption Layers                    │
├──────────────┬──────────────────────────────────────────────┤
│ Path         │ Algorithm                                    │
├──────────────┼──────────────────────────────────────────────┤
│ IPC (ZMQ)   │ None (UNIX domain sockets, local only)       │
│              │ [Optional] ZeroMQ CURVE (libsodium NaCl)    │
├──────────────┼──────────────────────────────────────────────┤
│ Cloud MQTT  │ Layer 1: TLS (mbedTLS) for transport         │
│              │ Layer 2: QLCloud application-layer encrypt:  │
│              │   CREPT_0: plaintext                        │
│              │   CREPT_1: custom rolling XOR               │
│              │   CREPT_2: AES-128-CBC                      │
│              │   CREPT_3/4: SM4-ECB / SM4-CBC              │
├──────────────┼──────────────────────────────────────────────┤
│ MCU Serial  │ AES-128-CTR (OpenSSL EVP, libtrifo_robot.so) │
│ /dev/ttyS3  │ + CRC-16/CCITT for packet integrity          │
├──────────────┼──────────────────────────────────────────────┤
│ Camera/Map  │ Shared memory only (no encryption)           │
│ /dev/shm/   │                                              │
└──────────────┴──────────────────────────────────────────────┘
```

---

## Cross-References

- See [Phase 1](01_process_architecture.md) for process topology and IPC socket names
- See [Phase 3](03_zeromq_services.md) for per-port ZeroMQ service details
- See [Phase 4](04_mcu_protocol.md) for detailed MCU serial protocol analysis
- See [Phase 5](05_cloud_protocol.md) for MQTT topic tree and cloud protocol reconstruction
- See [scripts/lucy_decrypt.py](../scripts/lucy_decrypt.py) for working encrypt/decrypt Python implementation
