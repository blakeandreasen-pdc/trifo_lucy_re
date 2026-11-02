"""
Read live map data from Lucy's shared memory over SSH.

Parses the SHM protobuf to extract the scan_map grid, dimensions,
and robot pose. Returns everything needed for web UI rendering.
"""
import subprocess
import struct
import time
import base64
import os

from lucy_live import SSH_KEY, SSH_HOST, SSH_OPTS

# SHM paths on Lucy
SHM_VISUAL_MAP = "/dev/shm/TrifoSemaphore_visual_mapper-multi_layer_map"
SHM_MAPPER_MAP = "/dev/shm/TrifoSemaphore_mapper-multi_layer_map"
SHM_HEADER_SIZE = 8192  # 0x2000 TrifoSemaphore header

# Cache to avoid hammering SSH
_map_cache = {"data": None, "time": 0, "ttl": 5}


def _ssh_grab(shm_path, grab_bytes=2097152, skip_header=False):
    """Grab bytes from Lucy's SHM via SSH. Returns bytes or None."""
    skip = SHM_HEADER_SIZE if skip_header else 0
    # dd: grab up to grab_bytes from the SHM
    dd_cmd = f"dd if={shm_path} bs=4096 skip={skip // 4096} count={grab_bytes // 4096} 2>/dev/null"
    full_cmd = ["ssh", "-i", SSH_KEY] + SSH_OPTS + [SSH_HOST, dd_cmd]
    try:
        r = subprocess.run(full_cmd, capture_output=True, timeout=15)
        if r.returncode == 0 and len(r.stdout) > 100:
            return r.stdout
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"[map_reader] SSH error: {e}")
    return None


def _decode_varint(data, pos):
    """Decode a protobuf varint. Returns (value, new_pos) or (None, pos)."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        result |= (b & 0x7F) << shift
        pos += 1
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            return None, pos
    return None, pos


def _parse_proto_fields(data, limit=None):
    """Parse protobuf fields from data. Returns list of (field_num, wire_type, value, raw_bytes)."""
    fields = []
    pos = 0
    end = len(data) if limit is None else min(limit, len(data))
    while pos < end:
        tag, new_pos = _decode_varint(data, pos)
        if tag is None:
            break
        field_num = tag >> 3
        wire_type = tag & 7
        if field_num == 0 or field_num > 500:
            break
        pos = new_pos

        if wire_type == 0:  # varint
            val, pos = _decode_varint(data, pos)
            if val is None:
                break
            fields.append((field_num, 0, val, None))
        elif wire_type == 1:  # 64-bit
            if pos + 8 > end:
                break
            val = struct.unpack_from('<d', data, pos)[0]
            fields.append((field_num, 1, val, data[pos:pos+8]))
            pos += 8
        elif wire_type == 2:  # length-delimited
            length, pos = _decode_varint(data, pos)
            if length is None or pos + length > len(data):
                break
            fields.append((field_num, 2, data[pos:pos+length], None))
            pos += length
        elif wire_type == 5:  # 32-bit
            if pos + 4 > end:
                break
            val = struct.unpack_from('<f', data, pos)[0]
            fields.append((field_num, 5, val, None))
            pos += 4
        else:
            break
    return fields


def _find_scan_map_grid(data):
    """Find and parse the scan_map grid from protobuf data.

    Uses pattern matching to find the GridMsg fields (cell_size double +
    height/width varints) near the "scan_map" key, handling arbitrary
    nesting wrappers.

    Returns dict with cell_size, height, width, max_x, max_y, grid_data
    or None if not found.
    """
    idx = data.find(b'scan_map')
    if idx < 0:
        return None

    # Search up to 200 bytes after "scan_map" for the GridMsg field pattern:
    # 0x09 (field 1, wire 1 = double) followed by 8 bytes, then
    # 0x10 (field 2, wire 0 = varint for height), then
    # 0x18 (field 3, wire 0 = varint for width)
    search_start = idx + 8
    search = data[search_start:search_start + 200]

    for i in range(len(search) - 20):
        if search[i] != 0x09:
            continue

        # Candidate cell_size (double)
        if i + 9 >= len(search):
            continue
        cell_size = struct.unpack_from('<d', search, i + 1)[0]
        if not (0.005 < cell_size < 0.2):
            continue

        # Height varint (field 2, tag 0x10)
        p = i + 9
        if p >= len(search) or search[p] != 0x10:
            continue
        p += 1
        height, p = _decode_varint(search, p)
        if height is None or height < 10 or height > 10000:
            continue

        # Width varint (field 3, tag 0x18)
        if p >= len(search) or search[p] != 0x18:
            continue
        p += 1
        width, p = _decode_varint(search, p)
        if width is None or width < 10 or width > 10000:
            continue

        result = {'cell_size': cell_size, 'height': height, 'width': width}

        # max_x (field 4, tag 0x21, wire 1 = double)
        if p < len(search) and search[p] == 0x21:
            result['max_x'] = struct.unpack_from('<d', search, p + 1)[0]
            p += 9

        # max_y (field 5, tag 0x29, wire 1 = double)
        if p < len(search) and search[p] == 0x29:
            result['max_y'] = struct.unpack_from('<d', search, p + 1)[0]
            p += 9

        # Grid data (field 6, tag 0x32, wire 2 = bytes)
        if p < len(search) and search[p] == 0x32:
            p += 1
            data_len, p = _decode_varint(search, p)
            if data_len and data_len == height * width:
                abs_offset = search_start + p
                if abs_offset + data_len <= len(data):
                    result['grid_data'] = data[abs_offset:abs_offset + data_len]
                    return result

    return None


_pose_cache = {"data": None, "time": 0, "ttl": 3}


def _grab_robot_pose():
    """Read robot pose from slam_node via strace on ZMQ sendto.

    Returns dict {x, y, theta} or None.
    """
    now = time.time()
    if _pose_cache["data"] and (now - _pose_cache["time"]) < _pose_cache["ttl"]:
        return _pose_cache["data"]

    # One message from her mapper's pose feed (a ZeroMQ PUB, /data/local/tmp/mapper-global_pose,
    # read with /data/lucy_local/zq; 2026-10-24). This replaced attaching strace to slam_node,
    # which slowed her navigation every time the map refreshed. Same Pose2D message.
    cmd = ("/data/lucy_local/zq /data/local/tmp/mapper-global_pose SUB - 600 | grep -m1 '^frame'")
    full_cmd = ["ssh", "-i", SSH_KEY] + SSH_OPTS + [SSH_HOST, cmd]
    try:
        r = subprocess.run(full_cmd, capture_output=True, timeout=10)
        line = r.stdout.decode(errors='replace').strip()
        if not line:
            return _pose_cache.get("data")
        data = bytes(2) + bytes.fromhex(line.rsplit(":", 1)[1].strip())

        # Skip 2-byte ZMQ header, parse Pose2DItemMsg
        proto = data[2:]
        pose = {}
        pos = 0
        while pos < len(proto):
            tag, new_pos = _decode_varint(proto, pos)
            if tag is None:
                break
            fn = tag >> 3
            wt = tag & 7
            if fn == 0 or fn > 20:
                break
            pos = new_pos
            if wt == 1 and pos + 8 <= len(proto):
                val = struct.unpack_from('<d', proto, pos)[0]
                if fn == 1:
                    pose['x'] = val
                elif fn == 2:
                    pose['y'] = val
                elif fn == 3:
                    pose['theta'] = val
                pos += 8
            elif wt == 0:
                val, pos = _decode_varint(proto, pos)
                if val is None:
                    break
            else:
                break

        sane = all(k in pose and abs(pose[k]) < 1000 for k in ('x', 'y', 'theta'))
        if sane:
            _pose_cache["data"] = pose
            _pose_cache["time"] = now
            return pose

    except Exception as e:
        print(f"[map_reader] Pose grab error: {e}")

    return _pose_cache.get("data")


_C_ESCAPES = {b'a': 7, b'b': 8, b't': 9, b'n': 10, b'v': 11, b'f': 12, b'r': 13,
              b'"': 34, b'\\': 92, b"'": 39}


def _parse_strace_bytes(raw):
    """Parse strace-escaped byte string to actual bytes."""
    data = bytearray()
    i = 0
    while i < len(raw):
        if raw[i:i+1] == b'\\' and i + 1 < len(raw):
            c = raw[i+1:i+2]
            if c == b'x' and i + 3 < len(raw):
                try:
                    data.append(int(raw[i+2:i+4], 16))
                    i += 4
                    continue
                except ValueError:
                    pass
            elif c.isdigit():
                end = i + 2
                while end < len(raw) and end < i + 4 and raw[end:end+1].isdigit():
                    end += 1
                data.append(int(raw[i+1:end], 8))
                i = end
                continue
            elif c in _C_ESCAPES:
                data.append(_C_ESCAPES[c]); i += 2; continue
        data.append(raw[i])
        i += 1
    return bytes(data)


def get_live_map(force=False):
    """Get the current map from Lucy's SHM.

    Returns dict:
        {
            "ok": True,
            "width": int,
            "height": int,
            "cell_size": float,
            "max_x": float,   # grid row    = (max_x - pose.x) / cell_size
            "max_y": float,   # grid column = (max_y - pose.y) / cell_size
            "cells_b64": str,  # base64-encoded raw grid bytes
            "timestamp": float,
        }
    Or {"ok": False, "error": str} on failure.
    """
    now = time.time()

    # Check cache
    if not force and _map_cache["data"] and (now - _map_cache["time"]) < _map_cache["ttl"]:
        return _map_cache["data"]

    # Try visual_map first (smaller), then mapper map
    for shm_path in [SHM_VISUAL_MAP, SHM_MAPPER_MAP]:
        raw = _ssh_grab(shm_path, grab_bytes=2097152)
        if raw is None:
            continue

        grid = _find_scan_map_grid(raw)
        if grid and 'grid_data' in grid:
            # Try to get robot pose
            pose = _grab_robot_pose()

            result = {
                "ok": True,
                "width": grid.get('width', 0),
                "height": grid.get('height', 0),
                "cell_size": grid.get('cell_size', 0.025),
                "max_x": grid.get('max_x', 0),
                "max_y": grid.get('max_y', 0),
                "cells_b64": base64.b64encode(grid['grid_data']).decode('ascii'),
                "timestamp": now,
                "source": os.path.basename(shm_path),
            }
            if pose:
                result["pose"] = pose
            _map_cache["data"] = result
            _map_cache["time"] = now
            return result

    return {"ok": False, "error": "Could not read map from Lucy SHM"}


def get_robot_pose():
    """Get robot pose from Lucy. Returns {x, y, theta} or None."""
    return _grab_robot_pose()


if __name__ == "__main__":
    import json
    print("Fetching live map from Lucy...")
    result = get_live_map(force=True)
    if result.get("ok"):
        print(f"Map: {result['width']}x{result['height']}, cell_size={result['cell_size']}")
        print(f"Bounds: max_x={result['max_x']}, max_y={result['max_y']}")
        print(f"Grid data: {len(base64.b64decode(result['cells_b64']))} bytes")
        print(f"Source: {result.get('source')}")
    else:
        print(f"Error: {result.get('error')}")
