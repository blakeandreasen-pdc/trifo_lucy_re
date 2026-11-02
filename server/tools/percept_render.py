"""Render Lucy's latest object-recognition class map (224x172, one class index per pixel)
in the model's label colours, with a legend of the classes present.

    python percept_render.py <percept.gz> <out.png>
"""
import gzip
import re
import struct
import sys
from collections import Counter

sys.path.insert(0, r"<server folder>")
from contact_sheet import write_png_rgb  # noqa: E402
from lucy_live import _fields  # noqa: E402

LABELS = [("unknown", (127, 140, 141)), ("bed", (249, 131, 159)), ("cabinet", (211, 84, 0)),
          ("chair", (245, 176, 65)), ("curtain", (244, 208, 63)), ("door", (214, 137, 16)),
          ("floor", (212, 172, 13)), ("large_container", (229, 152, 102)), ("rug", (84, 153, 199)),
          ("shoe", (245, 183, 177)), ("sock", (41, 128, 185)), ("sofa", (46, 134, 193)),
          ("table", (169, 223, 191)), ("wall", (253, 235, 208)), ("doorsill", (0, 255, 255)),
          ("wire", (169, 50, 38))]
W, H, N = 224, 172, 224 * 172

d = gzip.open(sys.argv[1]).read()
best = None
for m in re.finditer(rb"\x01\x00\x00\x00\x00\x00\x00\x00", d[:0x400000]):
    ts, ln = struct.unpack_from("<QQ", d, m.start() + 8)
    if ts > 10**12 and N < ln < 0x100000 and (best is None or ts > best[0]):
        best = (ts, m.start())
ts, i = best
ln = struct.unpack_from("<Q", d, i + 16)[0]
msg = d[i + 24:i + 24 + ln]


def find(b, depth=0):
    for fn, v in _fields(b):
        if isinstance(v, tuple):
            p, n = v
            if n == N:
                return b[p:p + n]
            if n > N and depth < 5:
                r = find(b[p:p + n], depth + 1)
                if r:
                    return r
    return None


mask = find(msg) or msg[-N:]
counts = Counter(mask)
print("ts", ts, "classes:", {LABELS[k][0] if k < len(LABELS) else k: v for k, v in counts.most_common()})
S = 3
rows = []
for r in range(H):
    line = bytearray()
    for c in range(W):
        k = mask[r * W + c]
        line += bytes(LABELS[k][1] if k < len(LABELS) else (255, 0, 255)) * S
    for _ in range(S):
        rows.append(bytes(line))
write_png_rgb(sys.argv[2], W * S, H * S, rows)
print(sys.argv[2])
