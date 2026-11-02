import gzip, struct, sys
sys.path.insert(0, r"<server folder>")
from lucy_live import _fields
from contact_sheet import write_png_rgb
d = gzip.open(r"captures\shm\depth.gz").read()
base, mo = 0x1000, 0x8c
one, ts, ln = struct.unpack_from("<QQQ", d, base+mo)
msg = d[base+mo+24: base+mo+24+ln]
W, H = 224, 172
N = W*H
def find_blob(b, size, depth=0):
    for fn, v in _fields(b):
        if isinstance(v, tuple):
            p, n = v
            if n == size: return b[p:p+n]
            if n > size and depth < 6:
                try:
                    r = find_blob(b[p:p+n], size, depth+1)
                    if r: return r
                except Exception: pass
    return None
# grab the inner field-3 message and its fields 5..8
outer = [v for fn, v in _fields(msg) if fn == 1 and isinstance(v, tuple)][1]
m1 = msg[outer[0]:outer[0]+outer[1]]
m2 = [v for fn, v in _fields(m1) if fn == 2][0]; m2 = m1[m2[0]:m2[0]+m2[1]]
m3 = [v for fn, v in _fields(m2) if fn == 3][0]; m3 = m2[m3[0]:m3[0]+m3[1]]
fields = {fn: m3[v[0]:v[0]+v[1]] for fn, v in _fields(m3) if isinstance(v, tuple)}
def gray_png(name, vals, lo, hi, scale=3):
    rows = []
    for r in range(H):
        line = bytearray()
        for c in range(W):
            x = vals[r*W + c]
            g = 0 if hi == lo else max(0, min(255, int((x - lo) * 255 / (hi - lo))))
            line += bytes((g, g, g)) * scale
        for _ in range(scale): rows.append(bytes(line))
    write_png_rgb(rf"captures\{name}.png", W*scale, H*scale, rows)
for fn in (5, 6):
    raw = find_blob(fields[fn], N) or fields[fn][-N:]
    vals = list(raw)
    s = sorted(vals); lo, hi = s[len(s)//50], s[-len(s)//50]
    print(fn, "u8 range", lo, hi); gray_png(f"tof_f{fn}", vals, lo, hi)
raw8 = find_blob(fields[8], N*4) or fields[8][-N*4:]
f32 = struct.unpack(f"<{N}f", raw8)
good = sorted(x for x in f32 if x == x and 0 < x < 20)
print("f8 float range", good[0] if good else None, good[-1] if good else None, "valid", len(good))
if good:
    lo, hi = good[len(good)//50], good[-len(good)//50]
    gray_png("tof_depth", [x if (x == x and 0 < x < 20) else hi for x in f32], hi, lo)   # near = bright
