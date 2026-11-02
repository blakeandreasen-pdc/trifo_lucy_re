"""3D scanner: close-range check on a capture. For frames with something near the centre of view, fit
a plane to the central patch and report flatness by distance; save a contact sheet of RGB stills.
  python tools/scan3d_close.py <dir> [t_start t_end]"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scan3d_read import H, W, records  # noqa: E402

root = Path(sys.argv[1])
t_a, t_b = (float(sys.argv[2]), float(sys.argv[3])) if len(sys.argv) > 3 else (0, 1e9)
rays = None
rows, stills, t0 = [], [], None
yy, xx = np.mgrid[56:116, 82:142]
for tag, ts, v in records(root / "stream.bin", keep_rgb=True):
    t0 = t0 or ts
    t = (ts - t0) / 1e6
    if tag == "P" and rays is None:
        z = v[..., 2]
        with np.errstate(all="ignore"):
            rays = (v[..., 0] / z, v[..., 1] / z)
    elif tag == "R":
        stills.append((t, v))
    elif tag == "D" and rays is not None and t_a <= t <= t_b:
        z = v["z"][56:116, 82:142]
        ok = (z > 0) & np.isfinite(rays[0][56:116, 82:142])
        if ok.sum() < 1500:
            continue
        x, y = (rays[0][56:116, 82:142] * z)[ok], (rays[1][56:116, 82:142] * z)[ok]
        zz = z[ok]
        A = np.c_[x, y, np.ones(len(zz))]
        for _ in range(3):  # trim outliers, the patch may not be all one face
            co, *_ = np.linalg.lstsq(A, zz, rcond=None)
            r = zz - A @ co
            s = 1.4826 * np.median(np.abs(r)) + 1e-5
            keep = np.abs(r) < 2.5 * s
            A, zz = A[keep], zz[keep]
        rows.append((t, np.median(z[ok]), s * 1000, keep.mean(), v["amp"][56:116, 82:142].max(), (v["amp"] >= 250).mean() * 100, (v["z"] > 0).mean()))
R = np.array(rows)
print(" dist cm   frames  plane_sd mm  inliers  amp_max  sat%  valid")
for a, b in [(0, 3), (3, 5), (5, 7), (7, 10), (10, 13), (13, 16), (16, 20), (20, 25), (25, 30), (30, 40), (40, 60)]:
    m = (R[:, 1] * 100 >= a) & (R[:, 1] * 100 < b)
    if m.sum():
        print(f"{a:3d}-{b:3d}   {m.sum():6d}   {np.median(R[m, 2]):8.2f}   {np.median(R[m, 3]):6.2f}   {np.median(R[m, 4]):5.0f}  {np.median(R[m, 5]):4.1f}   {np.median(R[m, 6]):.2f}")
print("closest centre z %.1f cm at t=%.0f" % (R[:, 1].min() * 100, R[R[:, 1].argmin(), 0]))
pick = [s for s in stills if t_a <= s[0] <= t_b]
pick = pick[:: max(1, len(pick) // 24)][:24]
tiles = []
for t, b in pick:
    yuv = np.frombuffer(b, np.uint8).reshape(1620, 1920)
    im = cv2.resize(cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12), (320, 180))
    cv2.putText(im, f"{t:.0f}s", (6, 22), 0, 0.7, (0, 255, 255), 2)
    tiles.append(im)
while len(tiles) % 6:
    tiles.append(np.zeros_like(tiles[0]))
cv2.imwrite(str(root / "stills.png"), np.vstack([np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]))
