import sys
sys.path.insert(0, r"<server folder>")
from contact_sheet import read_png_rgb, write_png_rgb
src, dst, x0, y0, x1, y1, k = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:8])
w, h, rows = read_png_rgb(src)
out = []
for y in range(y0, y1):
    r = rows[y]
    line = bytearray()
    for x in range(x0, x1):
        px = r[x*3:x*3+3]
        # stretch contrast a bit
        px = bytes(min(255, max(0, int((c - 40) * 1.6))) for c in px)
        line += px * k
    for _ in range(k):
        out.append(bytes(line))
write_png_rgb(dst, (x1-x0)*k, (y1-y0)*k, out)
print(dst)
