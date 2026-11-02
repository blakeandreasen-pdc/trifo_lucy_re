"""Read a scan3d stream.bin (see onrobot/depthdump.c).
  python tools/scan3d_read.py <dir>   prints a summary: rates, gaps, pose, range, IMU, status changes"""
import struct
import sys
from pathlib import Path

import numpy as np

W, H, N = 224, 172, 224 * 172
D_LEN = 45 + N * 4


def records(path, keep_rgb=False):
    """Yields (tag, ts_us, value). D -> dict(pose, z in metres, conf, amp); P -> points; R -> bytes or None."""
    with open(path, "rb") as f:
        while True:
            head = f.read(13)
            if len(head) < 13:
                return
            tag = head[:1].decode()
            ts, ln = struct.unpack("<QI", head[1:])
            if tag == "R" and not keep_rgb:
                f.seek(ln, 1)
                yield tag, ts, None
                continue
            b = f.read(ln)
            if len(b) < ln:
                return
            if tag == "D":
                q = b[:45]
                pose = struct.unpack("<ddddd", q[1:9] + q[10:18] + q[19:27] + q[28:36] + q[37:45])
                z = np.frombuffer(b, "<u2", N, 45).reshape(H, W) / 10000.0
                conf = np.frombuffer(b, np.uint8, N, 45 + N * 2).reshape(H, W)
                amp = np.frombuffer(b, np.uint8, N, 45 + N * 3).reshape(H, W)
                yield tag, ts, {"pose": pose, "z": z, "conf": conf, "amp": amp}
            elif tag == "P":
                yield tag, ts, np.frombuffer(b, "<f4").reshape(H, W, 3)
            else:
                yield tag, ts, b


def main():
    root = Path(sys.argv[1])
    D, R, P = [], [], 0
    for tag, ts, v in records(root / "stream.bin"):
        if tag == "D":
            z = v["z"]
            ok = z > 0
            D.append((ts, *v["pose"], ok.mean(), np.median(z[ok]) if ok.any() else 0, v["amp"].max()))
        elif tag == "R":
            R.append(ts)
        else:
            P += 1
    D = np.array(D)
    if not len(D):
        print("no depth frames")
        return
    t = (D[:, 0] - D[0, 0]) / 1e6
    gaps = np.diff(t)
    print(f"depth frames {len(D)} over {t[-1]:.0f} s, {len(D) / max(t[-1], 1):.1f} Hz; gap median {np.median(gaps) * 1000:.0f} ms, max {gaps.max():.1f} s, gaps over 1 s: {(gaps > 1).sum()}")
    print(f"rgb stills {len(R)}, point frames {P}")
    step = max(1, len(D) // 16)
    print("   t   valid  z_med amp_max      x      y     yaw    roll   pitch")
    for r, tt in zip(D[::step], t[::step]):
        print(f"{tt:5.0f}  {r[6]:.2f}  {r[7]:5.3f}  {int(r[8]):4d}  {r[1]:6.2f} {r[2]:6.2f} {r[3]:7.2f} {r[4]:7.3f} {r[5]:7.3f}")
    for name in ("imu.txt",):
        p = root / name
        if p.exists():
            L = p.read_text(errors="replace").splitlines()
            print(f"{name}: {len(L)} lines; " + " | ".join(x[:90] for x in L[:4]))
    p = root / "status.log"
    if p.exists():
        prev = None
        for line in p.read_text().splitlines():
            s = line.split(" ", 1)[1] if " " in line else line
            if s != prev:
                print("status", line)
            prev = s


if __name__ == "__main__":
    main()
