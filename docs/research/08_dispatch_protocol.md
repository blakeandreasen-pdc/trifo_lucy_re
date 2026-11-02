# Phase 8: QLCloud Dispatch Protocol & MQTT Traffic Capture

**Date**: 2026-03-08
**Status**: SUCCESS — Full dispatch decode + live MQTT capture achieved

## 1. Dispatch Protocol (port 7990)

### Overview

Lucy connects to `eudispatch.trifo.com:7990` over TLS 1.2 and exchanges binary packets using a custom QLCloud framing protocol. The dispatch server's role is to tell the device which MQTT broker to connect to.

All dispatch logic lives in `libtrifo_core_cloud.so` (QLCloud IoT SDK v3).

### Packet Format

Request and response share identical binary framing:

```
Offset  Size  Field
0       4     Nonce (32-bit big-endian; low byte = rolling XOR initial key)
4       2     Magic (16-bit big-endian; 0xf1eb=EU, 0xf1ec=US)
6       4     Data length N (32-bit big-endian)
10      N     Data payload (ASCII text)
10+N    2     CRC-16 checksum (16-bit big-endian)
```

Total packet size = N + 12 bytes.

### Encryption

- Algorithm: QLCloud rolling XOR cipher (same as MQTT message obfuscation)
- Seed: `0x7ecf` (hardcoded in SDK)
- Initial key: low byte of the 4-byte nonce (byte 3)
- Encrypted range: bytes `[4, total_len - 4)` — nonce (bytes 0-3) and CRC (last 2 bytes) are NOT encrypted
- The CRC is computed over the **decrypted** data (before encryption / after decryption)

### CRC Algorithm

- CRC-16/MODBUS: polynomial 0x8005 (reflected as 0xA001), init=0xFFFF
- Computed over bytes `[0, 10 + data_len)` of the **decrypted** packet

### Request Data

The request payload is the device's WiFi MAC address as ASCII with colons:
```
aa:bb:cc:dd:ee:ff
```
(17 bytes, making the total packet 29 bytes)

### Response Data

The response payload is the MQTT broker address as ASCII:
```
IP:PORT
```
Example: `192.168.1.35:17766` (18 bytes, total packet 30 bytes)

### Key Functions in `libtrifo_core_cloud.so`

| Function | Offset | Size | Purpose |
|---|---|---|---|
| `qlcloud_create_dispatch_request` | 0x1a4d64 | 264 | Builds dispatch request packet |
| `qlcloud_parse_dispatch_info` | 0x1a4f14 | 224 | Parses/validates dispatch response |
| `_parse_dispatch_ipinfo` | 0x1a4e6c | 168 | Extracts IP:PORT from response data |
| `qlcloud_get_dispatch_ipinfo` | 0x1a511c | 884 | Full dispatch flow (connect, send, recv, parse) |
| `qlcloud_open_dispatch_socket` | 0x1a4ff4 | 292 | Opens TLS connection to dispatch |
| `qlcloud_close_dispatch_socket` | 0x1a5118 | 4 | Closes dispatch socket |
| `ql_tcp_send_ssl` | 0x1a7b70 | 248 | TLS send wrapper |
| `ql_tcp_recv_ssl` | 0x1a7c68 | 184 | TLS receive wrapper |
| `crc16` | PLT→ext | — | CRC-16/MODBUS checksum |

### Magic Value Selection

Set in `qlcloud_get_dispatch_ipinfo` at offset 0x1a5190:
```
if config[4] == 1:    # EU
    magic = 0xf1eb
else:                 # US/other
    magic = 0xf1ec
```

### Connection Flow

1. Lucy resolves `eudispatch.trifo.com` → our server IP (via /etc/hosts)
2. TLS 1.2 handshake (ECDHE-RSA-AES256-GCM-SHA384, self-signed cert accepted)
3. Sends 29-byte dispatch request (MAC address)
4. Receives 30-byte dispatch response (broker IP:PORT)
5. Closes dispatch connection
6. Immediately connects to the broker IP on the specified port

### Example Decoded Request

```
Raw:     000041c6 <redacted sample> 9caf
Nonce:   0x000041c6 (key=0xc6)
Magic:   0xf1eb (EU)
DataLen: 17
Data:    aa:bb:cc:dd:ee:ff
CRC:     0x9caf ✓
```

## 2. MQTT Connection Details

### Connection Parameters

| Field | Value |
|---|---|
| Protocol | MQTT 3.1.1 (level 4) |
| Client ID | `aa:bb:cc:dd:ee:ff` (WiFi MAC) |
| Username | `**` (2 bytes — likely placeholder/auth token) |
| Password | `**` (2 bytes — likely placeholder/auth token) |
| Keep Alive | 5 seconds |
| Clean Session | Yes |
| Will Flag | No |
| TLS | TLSv1.2 (ECDHE-RSA-AES256-GCM-SHA384) |

### Topic Names

| Direction | Topic | Purpose |
|---|---|---|
| Subscribe (server→device) | `d/s/00000000-0000000` | Commands to device |
| Publish (device→server) | `d/p/00000000-0000000` | Data from device |

Topic format: `d/{s|p}/{number1}-{number2}`
- `d` = device namespace
- `s` = subscribe (inbound), `p` = publish (outbound)
- Numbers appear to be derived from product_id (1009506721) — likely a hash or encoding

### MQTT Payload Format

PUBLISH payloads have a 16-byte binary header followed by JSON:

```
Offset  Size  Field
0       4     Total payload length (32-bit BE, includes header)
4       2     Protocol/type: 0x0010
6       2     Subtype: 0x0201
8       2     Flags: 0x0100
10      2     More flags: 0x0101
12      4     Sequence number (32-bit BE, increments per message)
16      N     JSON payload
```

### Registration JSON (PUBLISH)

Lucy repeatedly publishes registration requests (every ~30 seconds):

```json
{
  "req": {
    "product_id": 1009506721
  },
  "data": {
    "product_sign": "gTViQn5Cc2/Z1y7hfsC1Jg==",
    "rand": 28604,
    "mac": "aa:bb:cc:dd:ee:ff",
    "pf": "20",
    "crypt_type": 1,
    "sn": "LUCXXXXXXXXXXXXX0"
  }
}
```

Key observations:
- `product_sign` is base64-encoded (16 bytes decoded), changes each message (new rand each time)
- `crypt_type: 1` indicates encryption mode for subsequent messages
- `pf: "20"` is the platform identifier (0x20 = 32, matches `%02x` format)
- `sn` is the real serial number from `/data/etc/trifo_config.json`
- `rand` is a fresh random number per attempt
- The product_sign is NOT the simple MD5 from Phase 2 — it's base64 and 16 bytes, suggesting HMAC-MD5 or similar

### Expected Server Response

Based on the JSON format strings found in the SDK:
```json
{"res": {"errcode": 0, "token": "..."}}
```

The device expects a response on its subscribe topic (`d/s/...`) containing an error code and token. Once registered, subsequent communication would use `dev_sign = MD5(device_secret + rand + dev_id)`.

## 3. Working Capture Server

The capture server (`mqtt_capture/capture_server.py`) successfully:

1. **Dispatch (port 7990)**: Accepts TLS connection, decodes dispatch request, sends correctly-framed response pointing to local MQTT broker
2. **MQTT (port 17766)**: Accepts TLS connection, responds to CONNECT/SUBSCRIBE/PUBLISH/PINGREQ
3. **HTTPS (port 443)**: Serves language pack config requests

### Key Code

Response builder:
```python
def qlcloud_build_dispatch_response(data_str, magic=0xf1eb):
    data_bytes = data_str.encode('ascii')
    data_len = len(data_bytes)
    total_len = 10 + data_len + 2
    buf = bytearray(total_len)
    nonce = random.randint(0, 0xFFFFFFFF)
    key = nonce & 0xFF
    struct.pack_into(">I", buf, 0, nonce)
    struct.pack_into(">H", buf, 4, magic)
    struct.pack_into(">I", buf, 6, data_len)
    buf[10:10 + data_len] = data_bytes
    crc = crc16_modbus(buf[0:10 + data_len])
    struct.pack_into(">H", buf, 10 + data_len, crc)
    qlcloud_encrypt(buf, 4, total_len - 4, key, 0x7ecf)
    return bytes(buf)
```

## 4. Identity Hash Analysis

The 20-byte constant in dispatch requests (`<redacted sample>`) is the encrypted form of `aa:bb:cc:dd:ee:ff` (MAC address) under the rolling XOR cipher. It appeared constant across packets because the MAC never changes — the varying bytes in each packet are the nonce and CRC.

## 5. Remaining Work

### Immediate Next Steps
- [ ] Craft a valid registration response on the subscribe topic to complete device registration
- [ ] Decode `product_sign` algorithm (base64, possibly HMAC-MD5 with product_key)
- [ ] Explore what happens when registration succeeds (status reports, command acceptance)

### For Full Local Control
- [ ] Implement a complete MQTT broker that handles the QLCloud protocol
- [ ] Map all MQTT message types (commands, status, OTA, etc.)
- [ ] Build a control interface that publishes commands on `d/s/...` topics

## 6. Files Modified/Created

- `mqtt_capture/capture_server.py` — Updated with correct QLCloud binary dispatch protocol
- `lucy_re/08_dispatch_protocol.md` — This document
