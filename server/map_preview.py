"""Small PNG previews of her saved maps (map slots), drawn from the pose_graph_map.pbstream itself.

The file is a Cartographer pbstream (found 2026-10-25): 8-byte magic, then chunks of
u64 length + gzip'd protobuf. Chunk 1 holds the pose graph: field 1 -> trajectory (4) ->
{submap (2) {pose (1) Rigid3d, submap_index (2)}, trajectory_id (3)}. Each later chunk with
field 10 is one of Lucy's multi-layer submaps: repeated layer (2) {submap_id (1)
{trajectory_id (1), submap_index (2)}, submap_2d (2) {local_pose (1), grid (4) {limits (1)
{resolution (1), max (2) {x, y}, cell_limits (3) {num_x (1), num_y (2)}}, cells (2) packed
int32}}}. Cells: 0 = unknown, else correspondence cost 0.1 + (v - 1) * 0.8 / 32766
(probability of a wall = 1 - cost). Cell (row, col) of a grid sits at x = max.x - (row + .5) r,
y = max.y - (col + .5) r in the submap's local frame; global = submap pose * local_pose^-1.

    python map_preview.py slot_name     (writes _previews/<slot>.png, prints its path)"""
import math
import os
import struct
import subprocess
import sys
import zlib

import numpy as np

import lucy_live

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_previews")
SLOTS = "/data/lucy_local/maps"
RES = 0.05            # preview cell size (m)


def _varint(b, i):
    v = s = 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7f) << s
        s += 7
        if c < 0x80:
            return v, i


def _fields(b):
    """-> list of (field, value): ints, floats (fixed64 as double, fixed32 as float), bytes."""
    out, i = [], 0
    while i < len(b):
        key, i = _varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 1:
            v = struct.unpack_from("<d", b, i)[0]
            i += 8
        elif wt == 5:
            v = struct.unpack_from("<f", b, i)[0]
            i += 4
        elif wt == 2:
            n, i = _varint(b, i)
            v = b[i:i + n]
            i += n
        else:
            raise ValueError(f"wire type {wt}")
        out.append((f, v))
    return out


def _get(b, f, default=None):
    for k, v in _fields(b):
        if k == f:
            return v
    return default


def _rigid(b):
    """Rigid3d -> (x, y, yaw)."""
    t, q = _get(b, 1, b""), _get(b, 2, b"")
    x, y = _get(t, 1, 0.0), _get(t, 2, 0.0)
    qz, qw = _get(q, 3, 0.0), _get(q, 4, 1.0)
    return x, y, 2 * math.atan2(qz, qw)


def _chunks(data):
    i = 8
    while i + 8 <= len(data):
        (n,) = struct.unpack_from("<Q", data, i)
        i += 8
        yield zlib.decompress(data[i:i + n], 47)
        i += n


def render(data):
    """pbstream bytes -> (RGB uint8 image, info dict)."""
    chunks = list(_chunks(data))
    poses = {}                                     # (traj, index) -> global (x, y, yaw)
    pg = _get(chunks[1], 1, b"")
    for f, traj in _fields(pg):
        if f != 4:
            continue
        tid = _get(traj, 3, 0)
        for g, sm in _fields(traj):
            if g == 2:
                poses[(tid, _get(sm, 2, 0))] = _rigid(_get(sm, 1, b""))
    walls, free = [], []
    for ch in chunks[2:]:
        for f, v in _fields(ch):
            if f != 10:
                continue
            for g, layer in _fields(v):
                if g != 2:
                    continue
                sid = _get(layer, 1, b"")
                key = (_get(sid, 1, 0), _get(sid, 2, 0))
                s2d = _get(layer, 2, b"")
                grid = _get(s2d, 4)
                if key not in poses or not grid:
                    continue
                lim = _get(grid, 1, b"")
                r = _get(lim, 1, 0.05)
                mx = _get(lim, 2, b"")
                maxx, maxy = _get(mx, 1, 0.0), _get(mx, 2, 0.0)
                cl = _get(lim, 3, b"")
                nx, ny = _get(cl, 1, 0), _get(cl, 2, 0)
                raw = _get(grid, 2, b"")
                vals, i = [], 0
                cells = np.zeros(nx * ny, np.int32)
                k = 0
                while i < len(raw) and k < len(cells):
                    cells[k], i = _varint(raw, i)
                    k += 1
                cells = cells.reshape(ny, nx)
                rows, cols = np.nonzero(cells)
                v = cells[rows, cols]
                prob = 1 - (0.1 + (v - 1) * 0.8 / 32766)
                lx = maxx - (rows + 0.5) * r
                ly = maxy - (cols + 0.5) * r
                # local -> global: submap pose * local_pose^-1
                ox, oy, oth = _rigid(_get(s2d, 1, b""))
                gx, gy, gth = poses[key]
                dth = gth - oth
                c, s = math.cos(dth), math.sin(dth)
                px, py = lx - ox, ly - oy
                X = gx + c * px - s * py
                Y = gy + s * px + c * py
                walls.append(np.stack([X, Y, prob - 0.5], 1))     # votes: + wall, - free
    V = np.concatenate(walls) if walls else np.zeros((1, 3))
    x0, x1 = V[:, 0].min(), V[:, 0].max()
    y0, y1 = V[:, 1].min(), V[:, 1].max()
    h, w = int((x1 - x0) / RES) + 3, int((y1 - y0) / RES) + 3
    score = np.zeros((h, w))
    rr = ((x1 - V[:, 0]) / RES).astype(int) + 1            # same orientation as the live map
    cc = ((y1 - V[:, 1]) / RES).astype(int) + 1
    np.add.at(score, (rr, cc), V[:, 2])                    # every submap and layer votes
    img = np.full((h, w, 3), 200, np.uint8)                # unknown: grey, as on the live map
    img[score < -0.2] = (255, 255, 255)
    img[score > 0.3] = (0, 0, 0)
    area = float((score < -0.2).sum()) * RES * RES
    return img, {"w_m": round(float(y1 - y0), 1), "h_m": round(float(x1 - x0), 1), "area_m2": round(area, 1),
                 "submaps": len(poses), "trajectories": len({k[0] for k in poses})}


def _png(img, path):
    from PIL import Image
    im = Image.fromarray(img)
    im.thumbnail((360, 360))
    im.save(path)


def preview(slot, size_bytes):
    """Cached preview for a slot; re-rendered when the file size changes. -> (png path, info)."""
    import json
    os.makedirs(CACHE, exist_ok=True)
    png = os.path.join(CACHE, f"{slot}.png")
    meta = os.path.join(CACHE, f"{slot}.json")
    try:
        info = json.load(open(meta, encoding="utf-8"))
        if info.get("size") == size_bytes and os.path.exists(png):
            return png, info
    except (OSError, ValueError):
        pass
    cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [
        lucy_live.SSH_HOST, f"cat {SLOTS}/{slot}/pose_graph_map.pbstream"]
    data = subprocess.run(cmd, capture_output=True, timeout=60).stdout
    if len(data) < 16:
        return None, {"error": "no map file in this slot"}
    img, info = render(data)
    info["size"] = len(data)
    _png(img, png)
    json.dump(info, open(meta, "w", encoding="utf-8"))
    return png, info


if __name__ == "__main__":
    if sys.argv[1].endswith(".pbstream"):
        img, info = render(open(sys.argv[1], "rb").read())
        _png(img, sys.argv[1] + ".png")
        print(info)
    else:
        print(preview(sys.argv[1], -1))
