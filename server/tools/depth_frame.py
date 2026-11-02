"""Decode one frame of Lucy's ToF depth SHM ring (/dev/shm/TrifoSemaphore_lucy_camera-depth_data).
Ring: 4 KiB header, slots of 1 MiB from 0x1000; slot k's meta (u64 1 | u64 ts_us | u64 len) is at
slot + 0x8c + 0x20*k, followed by the protobuf. The protobuf has repeated field 1 items:
  {1: 8, 2: {5: floats...}}            (small item, maybe pose/IMU at capture)
  {1: 6, 2: {3: {5: img 224x172 u8?, 6: img, 7: points 224x172 x (x,y,z float32),
                 8: 224x172 x 4 bytes}}}
Each blob starts with an 8-byte header (seen: width/height?)."""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lucy_live import _fields  # noqa: E402

W, H = 224, 172


def _sub(b, fn, want_type=None):
    for f, v in _fields(b):
        if f != fn or not isinstance(v, tuple):
            continue
        blob = b[v[0]:v[0] + v[1]]
        if want_type is None:
            return blob
        for f2, v2 in _fields(blob):
            if f2 == 1 and v2 == want_type:
                return blob
    return None


def slots(d):
    out = []
    for k in range(3):
        base = 0x1000 + k * 0x100000
        mo = base + 0x8c + 0x20 * k
        one, ts, ln = struct.unpack_from("<QQQ", d, mo)
        if one == 1 and 0 < ln < 0x100000:
            out.append((ts, d[mo + 24: mo + 24 + ln]))
    return sorted(out)


def decode(msg):
    item = _sub(msg, 1, want_type=6)
    inner = _sub(_sub(item, 2), 3)
    blobs = {f: inner[v[0]:v[0] + v[1]] for f, v in _fields(inner) if isinstance(v, tuple)}
    out = {"headers": {f: b[:8].hex(" ") for f, b in blobs.items() if len(b) >= 8}}
    pts = blobs.get(7)
    if pts and len(pts) >= 8 + W * H * 12:
        out["points"] = np.frombuffer(pts[8:8 + W * H * 12], "<f4").reshape(H, W, 3)
    for f in (5, 6):
        b = blobs.get(f)
        if b and len(b) >= 8 + W * H:
            out[f"img{f}"] = np.frombuffer(b[8:8 + W * H], np.uint8).reshape(H, W)
    b = blobs.get(8)
    if b and len(b) >= 8 + W * H * 4:
        out["f8"] = np.frombuffer(b[8:8 + W * H * 4], "<f4").reshape(H, W)
    return out


if __name__ == "__main__":
    d = Path(sys.argv[1]).read_bytes()
    ts, msg = slots(d)[-1]
    fr = decode(msg)
    print("ts", ts, fr["headers"])
    p = fr["points"]
    for name, i in (("x", 0), ("y", 1), ("z", 2)):
        v = p[..., i]
        ok = np.isfinite(v) & (v != 0)
        print(name, "valid", ok.sum(), "min %.3f max %.3f median %.3f" % (v[ok].min(), v[ok].max(), np.median(v[ok])))
    c = p[H // 2, W // 2]
    print("centre pixel", c, "f8 centre", fr["f8"][H // 2, W // 2])
