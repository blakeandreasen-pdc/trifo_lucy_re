"""
Live data from a rooted Lucy over SSH: shared SSH settings + camera snapshots.

The RGB camera writes 1920x1080 NV12 frames into a 3-slot ring in
/dev/shm/TrifoSemaphore_lucy_camera-image_data (one slot per 4 MiB).
Each slot holds:  u64 1 | u64 timestamp_us | u64 length | protobuf
where the protobuf wraps {width=1920, height=1080, data=<NV12 bytes>}.

The camera only streams while Lucy is active (cleaning, returning, etc.).
When she's docked the ring keeps the last frame, so every snapshot reports
its age and callers can tell a live frame from a stale one.
"""
import os
import struct
import subprocess
import time
import zlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_lucy_config():
    try:
        import yaml
        with open(os.path.join(BASE_DIR, "config.yaml")) as f:
            return (yaml.safe_load(f) or {}).get("lucy") or {}
    except Exception:
        return {}


_cfg = _load_lucy_config()
LUCY_IP = _cfg.get("ip", "YOUR_LUCY_IP")
SSH_KEY = os.path.expanduser(_cfg.get("ssh_key", "~/.ssh/trifo_lucy"))
SSH_HOST = f"root@{LUCY_IP}"
SSH_OPTS = [
    "-oKexAlgorithms=+diffie-hellman-group1-sha1",
    "-oHostKeyAlgorithms=+ssh-rsa",
    "-oMACs=+hmac-sha1",
    "-oPubkeyAcceptedAlgorithms=+ssh-rsa",
    "-oBatchMode=yes",
    "-oConnectTimeout=5",
    "-oStrictHostKeyChecking=no",
]

CAMERA_SHM = "/dev/shm/TrifoSemaphore_lucy_camera-image_data"
SLOT_STRIDE = 0x400000
SLOT_COUNT = 3
FRAME_W, FRAME_H = 1920, 1080
FRAME_BYTES = FRAME_W * FRAME_H * 3 // 2
META_MAGIC = b"\x01\x00\x00\x00\x00\x00\x00\x00"


def ssh_run(script, timeout=20):
    """Run a shell script on Lucy (fed via stdin). Returns stdout bytes or None."""
    cmd = ["ssh", "-i", SSH_KEY] + SSH_OPTS + [SSH_HOST, "sh -s"]
    try:
        r = subprocess.run(cmd, input=script.encode(), capture_output=True, timeout=timeout)
        return r.stdout
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"[lucy_live] SSH error: {e}")
        return None


# ---------------------------------------------------------------------------
# Protobuf helpers (just enough to walk the frame message)
# ---------------------------------------------------------------------------

def _varint(b, p):
    r = s = 0
    while True:
        c = b[p]
        p += 1
        r |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return r, p


def _fields(b):
    p, out = 0, []
    while p < len(b):
        tag, p = _varint(b, p)
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            v, p = _varint(b, p)
            out.append((fn, v))
        elif wt == 1:
            out.append((fn, b[p:p + 8]))
            p += 8
        elif wt == 5:
            out.append((fn, b[p:p + 4]))
            p += 4
        elif wt == 2:
            n, p = _varint(b, p)
            out.append((fn, (p, n)))
            p += n
        else:
            break
    return out


def _find_nv12(msg, base=0, depth=0):
    """Locate the NV12 payload (a bytes field of exactly FRAME_BYTES) inside the
    nested frame protobuf. Returns its offset within the top message, or None."""
    if depth > 6:
        return None
    try:
        fields = _fields(msg)
    except IndexError:
        return None
    for fn, v in fields:
        if not isinstance(v, tuple):
            continue
        p, n = v
        if n == FRAME_BYTES:
            return base + p
        if n > FRAME_BYTES:
            found = _find_nv12(msg[p:p + n], base + p, depth + 1)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

SNAPSHOT = "/dev/shm/lucy_live_snapshot"


def _parse_slot_metas(windows, base_offsets):
    """Find each slot's header (u64 1 | u64 ts | u64 len) in its 4 KB window.
    The length must be a full frame message, which rules out stray matches."""
    metas = []
    for k, (win, base) in enumerate(zip(windows, base_offsets)):
        i = win.find(META_MAGIC)
        while 0 <= i <= len(win) - 24:
            ts, length = struct.unpack_from("<QQ", win, i + 8)
            if ts > 0 and FRAME_BYTES < length < SLOT_STRIDE:
                metas.append({"slot": k, "meta_off": base + i, "ts": ts, "len": length})
                break
            i = win.find(META_MAGIC, i + 1)
    return metas


def grab_camera_frame():
    """Grab the newest complete camera frame.

    Returns dict {nv12: bytes, ts_us: int, age_s: float|None} or None.

    While the camera is live each slot is rewritten every ~150 ms, far faster
    than a WiFi transfer. So the first SSH call freezes the whole segment into
    a RAM snapshot on Lucy (~90 ms) and reports each slot's header; the second
    call transfers the chosen slot from that frozen copy. A slot that was being
    written during the snapshot fails validation and the next newest is used.
    """
    win_blocks = [k * (SLOT_STRIDE // 4096) + 1 for k in range(SLOT_COUNT)]
    script = (f"dd if={CAMERA_SHM} of={SNAPSHOT} bs=1048576 2>/dev/null\n"
              + "".join(f"dd if={SNAPSHOT} bs=4096 skip={b} count=1 2>/dev/null\n" for b in win_blocks)
              + "cat /proc/uptime\n")
    out = ssh_run(script)
    if not out or len(out) < SLOT_COUNT * 4096:
        return None
    windows = [out[k * 4096:(k + 1) * 4096] for k in range(SLOT_COUNT)]
    metas = _parse_slot_metas(windows, [b * 4096 for b in win_blocks])
    try:
        uptime = float(out[SLOT_COUNT * 4096:].split()[0])
    except (IndexError, ValueError):
        uptime = None

    frame = None
    candidates = sorted(metas, key=lambda m: m["ts"], reverse=True)[:2]
    if candidates:
        # Transfer the two newest slots in one go; validate newest first.
        script = ""
        spans = []
        for m in candidates:
            start = m["meta_off"] // 4096
            count = (m["meta_off"] + 24 + m["len"] - start * 4096 + 4095) // 4096
            script += f"dd if={SNAPSHOT} bs=4096 skip={start} count={count} 2>/dev/null\n"
            spans.append((m, start, count * 4096))
        raw = ssh_run(script + f"rm -f {SNAPSHOT}\n", timeout=30) or b""
        pos = 0
        for m, start, size in spans:
            chunk = raw[pos:pos + size]
            pos += size
            rel = m["meta_off"] - start * 4096
            if chunk[rel:rel + 8] != META_MAGIC:
                continue
            ts, length = struct.unpack_from("<QQ", chunk, rel + 8)
            msg = chunk[rel + 24:rel + 24 + length]
            off = _find_nv12(msg)
            if off is None or len(msg) < off + FRAME_BYTES:
                continue
            age = (uptime - ts / 1e6) if uptime else None
            frame = {"nv12": msg[off:off + FRAME_BYTES], "ts_us": ts, "age_s": age}
            break
    else:
        ssh_run(f"rm -f {SNAPSHOT}\n")
    return frame


def nv12_to_png(nv12, scale=2, white_balance=0.8):
    """Convert NV12 to an RGB PNG, downsampled by `scale` (2 or 4). Pure Python.

    The camera does no white balancing, so indoor light comes out very yellow.
    `white_balance` (0-1) pulls the average chroma towards neutral grey.
    """
    W, H = FRAME_W, FRAME_H
    uv0 = W * H
    out_w, out_h = W // scale, H // scale
    step = scale // 2  # UV samples are 2x2 blocks
    sample = nv12[uv0::194]  # even stride: alternates nothing, stays on U
    u_mean = sum(sample) / len(sample)
    sample = nv12[uv0 + 1::194]
    v_mean = sum(sample) / len(sample)
    u_off = 128 + int((u_mean - 128) * white_balance)
    v_off = 128 + int((v_mean - 128) * white_balance)
    rows = []
    for r in range(0, H, scale):
        ys = nv12[r * W:(r + 1) * W:scale]
        uv = nv12[uv0 + (r // 2) * W:uv0 + (r // 2 + 1) * W]
        line = bytearray(out_w * 3)
        for c in range(out_w):
            y = ys[c]
            u = uv[2 * c * step] - u_off
            v = uv[2 * c * step + 1] - v_off
            rr = y + ((359 * v) >> 8)
            gg = y - ((88 * u + 183 * v) >> 8)
            bb = y + ((454 * u) >> 8)
            j = 3 * c
            line[j] = 0 if rr < 0 else 255 if rr > 255 else rr
            line[j + 1] = 0 if gg < 0 else 255 if gg > 255 else gg
            line[j + 2] = 0 if bb < 0 else 255 if bb > 255 else bb
        rows.append(b"\x00" + bytes(line))

    def chunk(t, b):
        c = struct.pack(">I", len(b)) + t + b
        return c + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", out_w, out_h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
            + chunk(b"IEND", b""))


_cam_cache = {"png": None, "ts_us": None, "age_s": None, "time": 0}


def get_camera_png(scale=2, max_cache_s=1.0):
    """Return (png_bytes, info_dict) for the newest frame, or (None, error_dict)."""
    now = time.time()
    if _cam_cache["png"] and now - _cam_cache["time"] < max_cache_s:
        return _cam_cache["png"], {"ts_us": _cam_cache["ts_us"], "age_s": _cam_cache["age_s"], "cached": True}
    frame = grab_camera_frame()
    if not frame:
        return None, {"error": "could not read camera frame from Lucy"}
    if frame["ts_us"] == _cam_cache["ts_us"] and _cam_cache["png"]:
        png = _cam_cache["png"]  # same (stale) frame - skip the conversion
    else:
        png = nv12_to_png(frame["nv12"], scale)
    _cam_cache.update(png=png, ts_us=frame["ts_us"], age_s=frame["age_s"], time=now)
    return png, {"ts_us": frame["ts_us"], "age_s": frame["age_s"], "cached": False}


if __name__ == "__main__":
    import sys
    t0 = time.time()
    png, info = get_camera_png()
    if not png:
        print(info)
        sys.exit(1)
    path = sys.argv[1] if len(sys.argv) > 1 else "camera.png"
    with open(path, "wb") as f:
        f.write(png)
    age = info["age_s"]
    print(f"saved {path} ({len(png)} bytes) in {time.time() - t0:.1f}s; "
          f"frame age {age:.0f}s" if age is not None else "")
