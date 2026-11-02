"""Map melding: fold a piece of map (e.g. one room she was driven into) into her main map.

Her maps are Cartographer pbstreams (see map_preview.py for the layout). A map can hold several
trajectories (her 26 Oct map already has two, joined by 77 INTER_SUBMAP constraints), so a merge
is: renumber the piece's trajectory, move its global poses into the main map's frame, append its
submaps/nodes/constraints/options, and add INTER_SUBMAP constraints from the piece's nodes to
nearby main-map submaps so her optimiser keeps them together. Local poses are untouched (each
trajectory keeps its own local frame); constraints are relative, so only new ones are computed.

Chunks (each u64 length + gzip'd SerializedData proto):
  0 header {1: format version}, 1 pose_graph (1) {constraint (2), trajectory (4)},
  2 all_trajectory_builder_options (2) {one entry (1) per trajectory, in trajectory order},
  then node (4) {node_id (1) {trajectory_id, node_index}, node_data (5)} and Lucy's
  multi-layer submaps (10) {layer (2) {submap_id (1) {trajectory_id, submap_index}, ...}}.
Pose graph: trajectory {node (1) {timestamp (1), pose (5), node_index (7)}, submap (2)
  {pose (1), submap_index (2)}, trajectory_id (3)}; constraint {submap_id (1), node_id (2),
  relative_pose (3), tag (5) 1=INTER, translation_weight (6), rotation_weight (7)}.

    python map_merge.py selftest <map.pbstream>        split trajectories, nudge, re-find, rebuild
    python map_merge.py info <map.pbstream>
    python map_merge.py merge <main> <piece> <out> [--guess x,y,deg]
"""
import math
import struct
import sys
import zlib

import numpy as np

RES = 0.05
INTER_W = (11000.0, 100000.0)      # her own INTER_SUBMAP weights (translation, rotation)


# ---- protobuf, keeping wire types so untouched fields round-trip exactly
def _varint(b, i):
    v = s = 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7f) << s
        s += 7
        if c < 0x80:
            return v, i


def _enc_varint(v):
    out = bytearray()
    while True:
        c = v & 0x7f
        v >>= 7
        if v:
            out.append(c | 0x80)
        else:
            out.append(c)
            return bytes(out)


def dec(b):
    """bytes -> list of [field, wiretype, value] (value: int, raw 8/4 bytes, or bytes)."""
    out, i = [], 0
    while i < len(b):
        key, i = _varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 1:
            v, i = b[i:i + 8], i + 8
        elif wt == 5:
            v, i = b[i:i + 4], i + 4
        elif wt == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        else:
            raise ValueError(f"wire type {wt}")
        out.append([f, wt, v])
    return out


def enc(fields):
    out = bytearray()
    for f, wt, v in fields:
        out += _enc_varint(f << 3 | wt)
        if wt == 0:
            out += _enc_varint(v)
        elif wt == 2:
            out += _enc_varint(len(v)) + v
        else:
            out += v
    return bytes(out)


def get(b, f, default=None):
    for g, _, v in dec(b):
        if g == f:
            return v
    return default


def _dbl(v):
    return struct.unpack("<d", v)[0] if isinstance(v, bytes) else 0.0


def set_field(b, f, value, wt=2):
    """Replace (or add) field f of message b."""
    fs = [x for x in dec(b) if x[0] != f]
    fs.append([f, wt, value])
    fs.sort(key=lambda x: x[0])
    return enc(fs)


# ---- poses: Rigid3d {translation (1) {x,y,z}, rotation (2) {x,y,z,w}}; we work in 2D
def rigid_get(b):
    t, q = get(b, 1, b""), get(b, 2, b"")
    x, y = _dbl(get(t, 1)), _dbl(get(t, 2))
    qz, qw = _dbl(get(q, 3)), _dbl(get(q, 4)) if get(q, 4) is not None else 1.0
    return x, y, 2 * math.atan2(qz, qw)


def rigid_put(b, pose):
    """Write a 2D pose into Rigid3d b, keeping z (and any roll/pitch is assumed zero)."""
    x, y, th = pose
    t = get(b, 1, b"")
    tf = [g for g in dec(t) if g[0] == 3]
    t = enc([[1, 1, struct.pack("<d", x)], [2, 1, struct.pack("<d", y)]] + tf)
    q = enc([[3, 1, struct.pack("<d", math.sin(th / 2))], [4, 1, struct.pack("<d", math.cos(th / 2))]])
    return enc([[1, 2, t], [2, 2, q]])


def compose(a, b):
    ax, ay, at = a
    bx, by, bt = b
    c, s = math.cos(at), math.sin(at)
    return ax + c * bx - s * by, ay + s * bx + c * by, at + bt


def inverse(a):
    x, y, t = a
    c, s = math.cos(t), math.sin(t)
    return -c * x - s * y, s * x - c * y, -t


# ---- the map file
class PbMap:
    def __init__(self, data):
        self.magic = data[:8]
        self.chunks, i = [], 8
        while i + 8 <= len(data):
            (n,) = struct.unpack_from("<Q", data, i)
            self.chunks.append(zlib.decompress(data[i + 8:i + 8 + n], 47))
            i += 8 + n
        self.header = self.chunks[0]
        pg = get(self.chunks[1], 1)
        self.trajs = [v for f, _, v in dec(pg) if f == 4]
        self.cons = [v for f, _, v in dec(pg) if f == 2]
        self.pg_other = [x for x in dec(pg) if x[0] not in (2, 4)]
        self.opts = [v for f, _, v in dec(get(self.chunks[2], 2)) if f == 1]
        self.rest = self.chunks[3:]           # node (4) and submap (10) chunks, anything else

    @classmethod
    def load(cls, path):
        return cls(open(path, "rb").read())

    def tids(self):
        return [get(t, 3, 0) for t in self.trajs]

    def to_bytes(self):
        pg = enc(sorted([[2, 2, c] for c in self.cons] + [[4, 2, t] for t in self.trajs] + self.pg_other,
                        key=lambda x: x[0]))
        chunks = [self.header, enc([[1, 2, pg]]), enc([[2, 2, enc([[1, 2, o] for o in self.opts])]])] + self.rest
        out = bytearray(self.magic)
        for c in chunks:
            z = zlib.compressobj(6, zlib.DEFLATED, 31)
            g = z.compress(c) + z.flush()
            out += struct.pack("<Q", len(g)) + g
        return bytes(out)

    def save(self, path):
        open(path, "wb").write(self.to_bytes())

    # chunk helpers
    @staticmethod
    def chunk_tid(c):
        f, _, v = dec(c)[0]
        if f == 4:
            return get(get(v, 1, b""), 1, 0)
        if f == 10:
            for g, _, layer in dec(v):
                if g == 2:
                    return get(get(layer, 1, b""), 1, 0)
        return None

    def submap_poses(self, tid):
        t = self.trajs[self.tids().index(tid)]
        return {get(v, 2, 0): rigid_get(get(v, 1, b"")) for f, _, v in dec(t) if f == 2}

    def node_poses(self, tid):
        t = self.trajs[self.tids().index(tid)]
        return {get(v, 7, 0): rigid_get(get(v, 5, b"")) for f, _, v in dec(t) if f == 1}


def _set_tid_in_id(b, new):            # SubmapId / NodeId: trajectory_id is field 1
    return set_field(b, 1, new, 0)


def extract(m, tid, new_tid=None):
    """A copy of map m holding only trajectory tid (renumbered to new_tid)."""
    new_tid = tid if new_tid is None else new_tid
    out = PbMap.__new__(PbMap)
    out.magic, out.header, out.pg_other = m.magic, m.header, m.pg_other
    k = m.tids().index(tid)
    out.trajs = [set_field(m.trajs[k], 3, new_tid, 0)]
    out.opts = [m.opts[k]]
    out.cons = []
    for c in m.cons:
        a, b = get(get(c, 1), 1, 0), get(get(c, 2), 1, 0)
        if a == tid and b == tid:
            c = set_field(c, 1, _set_tid_in_id(get(c, 1), new_tid))
            out.cons.append(set_field(c, 2, _set_tid_in_id(get(c, 2), new_tid)))
    out.rest = []
    for c in m.rest:
        if PbMap.chunk_tid(c) != tid:
            continue
        f, wt, v = dec(c)[0]
        if f == 4:
            v = set_field(v, 1, _set_tid_in_id(get(v, 1), new_tid))
        elif f == 10:
            fs = []
            for g, w, layer in dec(v):
                if g == 2:
                    layer = set_field(layer, 1, _set_tid_in_id(get(layer, 1), new_tid))
                fs.append([g, w, layer])
            v = enc(fs)
        out.rest.append(enc([[f, wt, v]]))
    return out


def move(m, T):
    """Apply 2D transform T to every global pose in m (all trajectories)."""
    trajs = []
    for t in m.trajs:
        fs = []
        for f, w, v in dec(t):
            if f == 1:
                v = set_field(v, 5, rigid_put(get(v, 5, b""), compose(T, rigid_get(get(v, 5, b"")))))
            elif f == 2:
                v = set_field(v, 1, rigid_put(get(v, 1, b""), compose(T, rigid_get(get(v, 1, b"")))))
            fs.append([f, w, v])
        trajs.append(enc(fs))
    m.trajs = trajs
    return m


# ---- grids for alignment
def wall_points(m, tid=None, thresh=0.6):
    """Global (x, y) of wall cells (and free cells) from every submap layer."""
    poses = {}
    for t in m.trajs:
        k = get(t, 3, 0)
        for f, _, v in dec(t):
            if f == 2:
                poses[(k, get(v, 2, 0))] = rigid_get(get(v, 1, b""))
    walls, free = [], []
    for c in m.rest:
        f, _, v = dec(c)[0]
        if f != 10:
            continue
        for g, _, layer in dec(v):
            if g != 2:
                continue
            sid = get(layer, 1, b"")
            key = (get(sid, 1, 0), get(sid, 2, 0))
            if key not in poses or (tid is not None and key[0] != tid):
                continue
            s2d = get(layer, 2, b"")
            grid = get(s2d, 4)
            if not grid:
                continue
            lim = get(grid, 1, b"")
            r = _dbl(get(lim, 1)) or 0.05
            mx = get(lim, 2, b"")
            maxx, maxy = _dbl(get(mx, 1)), _dbl(get(mx, 2))
            cl = get(lim, 3, b"")
            nx, ny = get(cl, 1, 0), get(cl, 2, 0)
            raw, vals, i = get(grid, 2, b""), [], 0
            while i < len(raw):
                v2, i = _varint(raw, i)
                vals.append(v2)
            cells = np.array(vals[:nx * ny] + [0] * max(0, nx * ny - len(vals)), np.int64).reshape(ny, nx)
            rows, cols = np.nonzero(cells)
            prob = 1 - (0.1 + (cells[rows, cols] - 1) * 0.8 / 32766)
            lx, ly = maxx - (rows + 0.5) * r, maxy - (cols + 0.5) * r
            o, G = rigid_get(get(s2d, 1, b"")), poses[key]
            T = compose(G, inverse(o))
            cs, sn = math.cos(T[2]), math.sin(T[2])
            X, Y = T[0] + cs * lx - sn * ly, T[1] + sn * lx + cs * ly
            walls.append(np.stack([X, Y], 1)[prob > thresh])
            free.append(np.stack([X, Y], 1)[prob < 0.4])
    return (np.concatenate(walls) if walls else np.zeros((0, 2)),
            np.concatenate(free) if free else np.zeros((0, 2)))


def align(main_walls, piece_walls, guess=(0.0, 0.0, 0.0), span_m=1.5, span_deg=25):
    """Find T (piece frame -> main frame) that lays the piece's walls on the main map's walls.
    Coarse search (rotation steps, then translation by FFT correlation against a blurred wall
    image), then a fine pass around the best. Returns (T, score 0..1 = share of piece wall cells
    landing on main walls)."""
    from scipy import ndimage, signal
    lo = main_walls.min(0) - span_m - 3
    hi = main_walls.max(0) + span_m + 3
    shape = tuple(((hi - lo) / RES).astype(int) + 1)
    M = np.zeros(shape)
    ij = ((main_walls - lo) / RES).astype(int)
    M[ij[:, 0], ij[:, 1]] = 1
    near = ndimage.distance_transform_edt(M == 0) * RES
    field = np.exp(-(near / 0.07) ** 2)                 # 1 on a wall, fading by ~10 cm
    hit = (near <= 0.075).astype(float)

    def score_at(T, pts, img):
        c, s = math.cos(T[2]), math.sin(T[2])
        P = np.stack([T[0] + c * pts[:, 0] - s * pts[:, 1], T[1] + s * pts[:, 0] + c * pts[:, 1]], 1)
        k = ((P - lo) / RES).astype(int)
        ok = (k[:, 0] >= 0) & (k[:, 1] >= 0) & (k[:, 0] < shape[0]) & (k[:, 1] < shape[1])
        return img[k[ok, 0], k[ok, 1]].sum() / max(1, len(pts))

    pts = np.unique((piece_walls / RES).round().astype(int), axis=0) * RES
    best = (-1, guess)
    for deg_step, span_d, span_t in ((1.0, span_deg, span_m), (0.2, 1.5, 0.15)):
        g = best[1] if best[0] >= 0 else guess
        for dd in np.arange(-span_d, span_d + 1e-9, deg_step):
            th = g[2] + math.radians(dd)
            c, s = math.cos(th), math.sin(th)
            R = np.stack([c * pts[:, 0] - s * pts[:, 1], s * pts[:, 0] + c * pts[:, 1]], 1)
            # image of the rotated piece; corr[a] = piece cell k laid on main cell a + k, i.e.
            # translation t = lo + a * RES - Rmin
            Rmin = R.min(0)
            k = ((R - Rmin) / RES).round().astype(int)
            P = np.zeros(tuple(k.max(0) + 1))
            P[k[:, 0], k[:, 1]] = 1
            corr = signal.fftconvolve(field, P[::-1, ::-1], mode="valid")
            a0 = np.round((Rmin + np.array(g[:2]) - lo) / RES).astype(int)
            w = int(round(span_t / RES))
            a_lo, a_hi = np.maximum(a0 - w, 0), np.minimum(a0 + w + 1, corr.shape)
            win = corr[a_lo[0]:a_hi[0], a_lo[1]:a_hi[1]]
            if win.size == 0:
                continue
            ia, ib = np.unravel_index(np.argmax(win), win.shape)
            sc = win[ia, ib] / len(pts)
            if sc > best[0]:
                t = lo + (a_lo + np.array([ia, ib])) * RES - Rmin
                best = (sc, (float(t[0]), float(t[1]), th))
    T = best[1]
    return T, float(score_at(T, pts, hit))


def add_links(m, piece_tid, max_dist=1.5, every=3):
    """INTER_SUBMAP constraints from some of the piece's nodes to the nearest other-trajectory
    submaps (within max_dist of the submap origin), so her optimiser keeps the piece in place."""
    others = {}
    for k in m.tids():
        if k != piece_tid:
            for i, p in m.submap_poses(k).items():
                others[(k, i)] = p
    nodes = sorted(m.node_poses(piece_tid).items())[::every]
    added = 0
    for ni, npose in nodes:
        near = sorted(others.items(), key=lambda kv: math.hypot(kv[1][0] - npose[0], kv[1][1] - npose[1]))[:2]
        for (k, si), sp in near:
            if math.hypot(sp[0] - npose[0], sp[1] - npose[1]) > max_dist:
                continue
            rel = compose(inverse(sp), npose)
            sid = enc([[1, 0, k]] + ([[2, 0, si]] if si else []))
            nid = enc([[1, 0, piece_tid]] + ([[2, 0, ni]] if ni else []))
            m.cons.append(enc([[1, 2, sid], [2, 2, nid], [3, 2, rigid_put(b"", rel)], [5, 0, 1],
                               [6, 1, struct.pack("<d", INTER_W[0])], [7, 1, struct.pack("<d", INTER_W[1])]]))
            added += 1
    return added


def combine(main, piece, T, links=True):
    """main + piece (moved by T, renumbered to the next free trajectory id) -> new PbMap."""
    new_tid = max(main.tids()) + 1
    pt = piece.tids()
    if len(pt) != 1:
        raise ValueError("piece should hold one trajectory")
    p = move(extract(piece, pt[0], new_tid), T)
    out = PbMap.__new__(PbMap)
    out.magic, out.header, out.pg_other = main.magic, main.header, main.pg_other
    out.trajs = main.trajs + p.trajs
    out.opts = main.opts + p.opts
    out.cons = main.cons + p.cons
    out.rest = main.rest + p.rest
    n = add_links(out, new_tid) if links else 0
    return out, new_tid, n


def info(m):
    for k in m.tids():
        w, f = wall_points(m, k)
        print(f"trajectory {k}: {len(m.submap_poses(k))} submaps, {len(m.node_poses(k))} nodes, "
              f"{len(f) * RES * RES:.1f} m2 free cells (summed over layers)")
    print(f"{len(m.cons)} constraints, {len(m.rest)} node/submap chunks")


def selftest(path):
    import map_preview
    orig = PbMap.load(path)
    raw = open(path, "rb").read()
    re_ = PbMap(orig.to_bytes())
    same = [a == b for a, b in zip(PbMap(orig.to_bytes()).chunks, orig.chunks)]
    print("round trip: chunks identical:", all(same), f"({sum(same)}/{len(same)})")
    t1, t2 = orig.tids()[:2]
    A, B = extract(orig, t1), extract(orig, t2)
    nudge = (0.45, -0.3, math.radians(9))
    Bn = move(extract(orig, t2), nudge)
    wA, _ = wall_points(A)
    wB, _ = wall_points(Bn)
    T, sc = align(wA, wB)
    want = inverse(nudge)
    print(f"nudged by {nudge[0]:+.2f} m, {nudge[1]:+.2f} m, {math.degrees(nudge[2]):+.1f} deg; "
          f"found {T[0]:+.3f}, {T[1]:+.3f}, {math.degrees(T[2]):+.2f} deg (want {want[0]:+.3f}, {want[1]:+.3f}, "
          f"{math.degrees(want[2]):+.2f}); walls on walls {sc:.0%}")
    M, tid, n = combine(A, Bn, T)
    M.save(path + ".selftest.pbstream")
    img0, i0 = map_preview.render(raw)
    img1, i1 = map_preview.render(M.to_bytes())
    print("original", i0, "\nrebuilt ", i1, f"\n{n} links added; written {path}.selftest.pbstream")
    map_preview._png(img0, path + ".orig.png")
    map_preview._png(img1, path + ".selftest.png")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selftest":
        selftest(sys.argv[2])
    elif cmd == "info":
        info(PbMap.load(sys.argv[2]))
    elif cmd == "merge":
        main_m, piece = PbMap.load(sys.argv[2]), PbMap.load(sys.argv[3])
        guess = (0.0, 0.0, 0.0)
        if "--guess" in sys.argv:
            gx, gy, gd = map(float, sys.argv[sys.argv.index("--guess") + 1].split(","))
            guess = (gx, gy, math.radians(gd))
        wA, _ = wall_points(main_m)
        wB, _ = wall_points(piece)
        T, sc = align(wA, wB, guess)
        print(f"fit: {T[0]:+.3f} m, {T[1]:+.3f} m, {math.degrees(T[2]):+.2f} deg; walls on walls {sc:.0%}")
        out, tid, n = combine(main_m, piece, T)
        out.save(sys.argv[4])
        print(f"piece is trajectory {tid}; {n} links; written {sys.argv[4]}")
    else:
        print(__doc__)
