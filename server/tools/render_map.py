"""Render Lucy's live map to PNG with named places and her pose marked.

    python render_map.py [out.png]

Map transform (from memory notes): row = (max_x - x)/cs, col = (max_y - y)/cs.
Output is rotated so +x points up and +y points left (as she sees the map frame).
"""
import base64
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "tools"))
import map_reader  # noqa: E402
from contact_sheet import write_png_rgb  # noqa: E402
from goto import PLACES  # noqa: E402

m = map_reader.get_live_map(force=True)
w, h, cs = m["width"], m["height"], m["cell_size"]
cells = base64.b64decode(m["cells_b64"])
print("value histogram:", Counter(cells).most_common(8))


def colour(v):
    if v == 128:
        return (60, 60, 60)          # unknown
    if v < 128:                      # free (0) .. uncertain
        g = 250 - v
        return (g, g, g)
    return (20, 20, 120 + (v - 128) // 2)   # occupied (255 = wall)


SCALE = 2
img = [[colour(cells[r * w + c]) for c in range(w)] for r in range(h)]


def mark(x, y, rgb, size=4):
    r = int((m["max_x"] - x) / cs)
    c = int((m["max_y"] - y) / cs)
    for dr in range(-size, size + 1):
        for dc in range(-size, size + 1):
            if 0 <= r + dr < h and 0 <= c + dc < w and (abs(dr) == size or abs(dc) == size or (dr == 0 or dc == 0)):
                img[r + dr][c + dc] = rgb


for name, (x, y) in PLACES.items():
    mark(x, y, (220, 30, 30))
# 1 m grid ticks
for gx in range(-3, 6):
    for gy in range(-3, 8):
        mark(gx, gy, (0, 170, 0), 1)
if m.get("pose"):
    mark(m["pose"]["x"], m["pose"]["y"], (255, 160, 0), 6)

rows = []
for r in range(h):
    line = bytearray()
    for c in range(w):
        line += bytes(img[r][c]) * SCALE
    for _ in range(SCALE):
        rows.append(bytes(line))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "captures", "map_render.png")
write_png_rgb(out, w * SCALE, h * SCALE, rows)
print(out, "| rows=x (top = max_x %.2f), cols=y (left = max_y %.2f); green dots = 1 m grid" % (m["max_x"], m["max_y"]))
