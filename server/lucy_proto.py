"""
Minimal protobuf + LZ4 helpers for Lucy's map-management protocol (pure stdlib).

Message definitions: see lucy_protos_full.proto (cloud_map_manage_msg.proto),
rebuilt from the firmware by tools/extract_protos.py.
"""
import struct

# ---------------------------------------------------------------------------
# LZ4 block format (what the app's LZ4Factory.safeDecompressor() handles)
# ---------------------------------------------------------------------------

def lz4_block_decompress(src, max_out=1 << 26):
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:
            break  # last sequence has literals only
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - off
        if off == 0 or start < 0:
            raise ValueError("bad LZ4 offset")
        for k in range(ml):  # byte-wise: matches may overlap
            dst.append(dst[start + k])
        if len(dst) > max_out:
            raise ValueError("LZ4 output too large")
    return bytes(dst)


def lz4_block_compress_literals(data):
    """Encode `data` as a valid LZ4 block made of one literal-only sequence.
    No actual compression - but every LZ4 decoder accepts it."""
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    out = bytearray([0xF0])
    rest = n - 15
    while rest >= 255:
        out.append(255)
        rest -= 255
    out.append(rest)
    return bytes(out) + data


# ---------------------------------------------------------------------------
# Protobuf encode / decode
# ---------------------------------------------------------------------------

def _varint(v):
    if v < 0:
        v += 1 << 64
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_varint(field, value):
    return _varint(field << 3) + _varint(value)


def pb_bytes(field, data):
    if isinstance(data, str):
        data = data.encode()
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def pb_double(field, value):
    return _varint((field << 3) | 1) + struct.pack("<d", value)


def pb_float(field, value):
    return _varint((field << 3) | 5) + struct.pack("<f", value)


def _read_varint(b, p):
    r = s = 0
    while True:
        c = b[p]
        p += 1
        r |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return r, p


def pb_decode(b):
    """Decode to {field: [values]}; length-delimited values stay as bytes."""
    out = {}
    p = 0
    while p < len(b):
        tag, p = _read_varint(b, p)
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            v, p = _read_varint(b, p)
        elif wt == 1:
            v = struct.unpack_from("<d", b, p)[0]
            p += 8
        elif wt == 5:
            v = struct.unpack_from("<f", b, p)[0]
            p += 4
        elif wt == 2:
            n, p = _read_varint(b, p)
            v = b[p:p + n]
            p += n
        else:
            raise ValueError(f"wire type {wt}")
        out.setdefault(fn, []).append(v)
    return out


def pb_dump(b, depth=0, max_depth=6, indent="  "):
    """Best-effort recursive pretty-print of an unknown protobuf."""
    lines = []
    try:
        d = pb_decode(b)
    except Exception:
        return None
    for fn in sorted(d):
        for v in d[fn]:
            pre = indent * depth + f"{fn}: "
            if isinstance(v, bytes):
                sub = pb_dump(v, depth + 1, max_depth) if depth < max_depth and v else None
                if sub:
                    lines.append(pre + "{")
                    lines += sub
                    lines.append(indent * depth + "}")
                else:
                    try:
                        s = v.decode()
                        if not s.isprintable():
                            raise ValueError
                        lines.append(pre + repr(s))
                    except (UnicodeDecodeError, ValueError):
                        lines.append(pre + f"<{len(v)} bytes>")
            else:
                lines.append(pre + repr(v))
    return lines


# ---------------------------------------------------------------------------
# MapManageDataItemMsg builders
# ---------------------------------------------------------------------------

GET, POST, DELETE, RUN, REFRESH = range(5)
TYPE_LIST, TYPE_INFO, TYPE_PATH, TYPE_PATH_COMMAND, TYPE_LAYER = range(5)
NO_GO_ZONE, DESIGNATED_AREA, PATROL_ROUTE, ROOM_SEGMENTATION, SEMANTIC_INSTANCE = range(5)


def map_manage(command, mtype, map_info=None, map_paths=None, path_command=None):
    msg = pb_varint(1, command) + pb_varint(3, mtype)
    if map_info is not None:
        msg += pb_bytes(5, map_info)
    if map_paths is not None:
        msg += pb_bytes(6, map_paths)
    if path_command is not None:
        msg += pb_bytes(7, path_command)
    return msg


def one_map_info(map_id, name=None):
    msg = pb_varint(1, map_id)
    if name is not None:
        msg += pb_bytes(3, name)
    return msg


def map_path_info(map_id, path_type):
    return pb_varint(1, map_id) + pb_varint(2, path_type)


def path_command(map_id, path_type, path_ids):
    msg = pb_varint(1, map_id) + pb_varint(2, path_type)
    for pid in path_ids:
        msg += pb_varint(3, pid)
    return msg
