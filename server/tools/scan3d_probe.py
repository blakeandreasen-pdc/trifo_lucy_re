"""3D scanner side quest: test colouring Lucy's ToF cloud from her RGB camera, on snapshots of the
depth and image SHM rings. Prints timing and noise, writes a coloured PLY, an alignment check image
(depth edges over the RGB) and an oblique render.
  python tools/scan3d_probe.py captures/scan3d [calib_lucy|camera_info]"""
import json
import struct
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from depth_frame import H, W, decode, slots  # noqa: E402

DUMP = Path(__file__).resolve().parent.parent.parent / "Lucy Dump" / "app"


def load_calib(which):
    if which == "camera_info":
        c = json.loads((DUMP / "camera_info_file_name.txt").read_text())
        K = np.array(c["rgb_intrinsics"], float)
        D = np.array(c["rgb_distortion"], float).ravel()
        T = np.array(c["rgb_T_depth"], float)
    else:
        n = json.loads((DUMP / "calib" / "calib_lucy.json").read_text())
        cam = n["children"]["child_15"]["children"]["child_0"]["children"]["child_0"]
        K = np.array(cam["model"]["camera_matrix"], float)
        D = np.array(cam["model"]["distortion"], float).ravel()
        T = np.array(cam["children"]["child_0"]["parent_T_this"], float)
    return K, D, T


def rgb_slots(d):
    out = []
    for k in range(3):
        base = 0x1000 + k * 0x400000
        mo = base + 0x8c + 0x20 * k
        one, ts, ln = struct.unpack_from("<QQQ", d, mo)
        if one == 1 and 0 < ln < 0x400000:
            out.append((ts, mo + 24, ln))
    return sorted(out)


def rgb_image(d, off, ln):
    n = 1920 * 1080 * 3 // 2
    msg = d[off:off + ln]
    # {1: width, 2: height, 3: bytes}: the pixels are the last n bytes of the message
    yuv = np.frombuffer(msg[ln - n:ln], np.uint8).reshape(1620, 1920)
    return cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_NV12)


def project(pts, K, D, T):
    p = pts.reshape(-1, 3).astype(np.float64)
    ok = np.isfinite(p).all(1) & (p[:, 2] > 0.05)
    q = (T[:3, :3] @ p[ok].T).T + T[:3, 3]
    uv, _ = cv2.projectPoints(q, np.zeros(3), np.zeros(3), K, D)
    return ok, uv.reshape(-1, 2), q


def main():
    root = Path(sys.argv[1])
    which = sys.argv[2] if len(sys.argv) > 2 else "calib_lucy"
    frames = {}
    for f in sorted(root.glob("d*.bin")):
        for ts, msg in slots(f.read_bytes()):
            frames[ts] = msg
    ts = sorted(frames)
    dt = np.diff(ts) / 1000
    print(f"depth: {len(ts)} distinct frames; gaps ms min {dt.min():.0f} median {np.median(dt):.0f} max {dt.max():.0f}")
    fr = [decode(frames[t]) for t in ts]
    z = np.stack([f["points"][..., 2] for f in fr])
    z[z <= 0] = np.nan
    print("valid px per frame", [int(np.isfinite(a).sum()) for a in z][:6], "of", W * H)
    centre = np.nanmedian(z, 0)
    print(f"range: {np.nanmin(z):.3f} to {np.nanmax(z):.3f} m; median {np.nanmedian(z):.3f}")
    sd = np.nanstd(z, 0)
    for a, b in ((0.1, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 2.0), (2.0, 4.0)):
        m = (centre >= a) & (centre < b)
        if m.sum() > 100:
            print(f"  {a}-{b} m: {m.sum():6d} px, frame-to-frame sd median {np.nanmedian(sd[m]) * 1000:.1f} mm")
    print("blob fields:", fr[0]["headers"])
    # the small item (first in each message) next to the depth blob
    from lucy_live import _fields  # noqa
    m0 = frames[ts[-1]]
    for fn, v in _fields(m0):
        if isinstance(v, tuple) and v[1] < 4000:
            print("small item, len", v[1], m0[v[0]:v[0] + v[1]][:120].hex(" "))

    d = (root / "rgb.bin").read_bytes()
    rs = rgb_slots(d)
    print("rgb slots ts:", [t for t, _, _ in rs])
    rts, off, ln = rs[-1]
    nearest = min(ts, key=lambda t: abs(t - rts))
    print(f"newest rgb vs nearest depth: {(rts - nearest) / 1000:.0f} ms")
    img = rgb_image(d, off, ln)
    cv2.imwrite(str(root / "rgb.png"), img)
    print("rgb mean brightness", img.mean())

    K, D, T = load_calib(which)
    pts = fr[ts.index(nearest)]["points"]
    # noise down: median of the static frames
    all_pts = np.stack([f["points"] for f in fr])
    all_pts[all_pts == 0] = np.nan
    pts = np.nanmedian(all_pts, 0)
    ok, uv, q = project(pts, K, D, T)
    ui, vi = np.round(uv[:, 0]).astype(int), np.round(uv[:, 1]).astype(int)
    inside = (ui >= 0) & (ui < 1920) & (vi >= 0) & (vi < 1080)
    print(f"cloud pts {ok.sum()}, landing inside the RGB frame {inside.sum()} ({100 * inside.mean():.0f}%)")
    colour = img[vi[inside], ui[inside]]
    xyz = pts.reshape(-1, 3)[ok][inside]
    with open(root / f"cloud_{which}.ply", "w") as f:
        f.write(f"ply\nformat ascii 1.0\nelement vertex {len(xyz)}\nproperty float x\nproperty float y\nproperty float z\n"
                "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
        for p, c in zip(xyz, colour):
            f.write(f"{p[0]:.4f} {-p[1]:.4f} {-p[2]:.4f} {c[2]} {c[1]} {c[0]}\n")

    # alignment check: depth discontinuities drawn over the RGB
    zz = np.nan_to_num(pts[..., 2], nan=0).astype(np.float32)
    edges = (np.abs(cv2.Sobel(zz, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(zz, cv2.CV_32F, 0, 1))) > 0.25
    flat_ok = np.zeros(W * H, bool)
    idx = np.where(ok)[0][inside]
    flat_ok[idx] = True
    em = edges.ravel() & flat_ok
    lookup = np.full(W * H, -1)
    lookup[np.where(ok)[0]] = np.arange(ok.sum())
    over = img.copy()
    for i in np.where(em)[0]:
        j = lookup[i]
        cv2.circle(over, (ui[j], vi[j]), 3, (0, 255, 0), -1)
    cv2.imwrite(str(root / f"align_{which}.png"), cv2.resize(over, (1280, 720), interpolation=cv2.INTER_AREA))

    # oblique render: splat points after turning the view 30 degrees about the vertical
    a = np.radians(30)
    R = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    c0 = np.median(xyz, 0)
    v = (R @ (xyz - c0).T).T + [0, 0, np.median(xyz[:, 2])]
    f = 500.0
    canvas = np.full((720, 960, 3), 30, np.uint8)
    order = np.argsort(-v[:, 2])
    for i in order:
        if v[i, 2] <= 0.05:
            continue
        x, y = int(480 + f * v[i, 0] / v[i, 2]), int(360 + f * v[i, 1] / v[i, 2])
        if 0 <= x < 960 and 0 <= y < 720:
            cv2.circle(canvas, (x, y), 2, tuple(int(k) for k in colour[i]), -1)
    cv2.imwrite(str(root / f"oblique_{which}.png"), canvas)
    # a plain depth view too
    vis = np.clip(1 - np.nan_to_num(pts[..., 2], nan=5) / 3, 0, 1)
    cv2.imwrite(str(root / "depth.png"), cv2.resize(cv2.applyColorMap((vis * 255).astype(np.uint8), cv2.COLORMAP_TURBO), (672, 516), interpolation=cv2.INTER_NEAREST))


if __name__ == "__main__":
    main()
