r"""Bump test: drive slowly straight ahead until her bumper stops her, then compare with her map.
    python tools\bump_calib.py [speed=3] [max_dist=1.2]
At the bump the real gap in front of her is ~0. The script prints what her map says the gap is
(nearest occupied cell in a 35 cm-wide corridor straight ahead, measured from her front edge),
before and after, plus how far her pose says she moved. Same error from different spots = an
offset in our maths; different errors = her own pose drift."""
import json
import math
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import base64

ROOT = Path(__file__).resolve().parent.parent
BODY_R = 0.175


def get(path):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8090" + path, timeout=30))


def front_gap(m, p, half=BODY_R, occ=170):
    a = np.frombuffer(base64.b64decode(m["cells_b64"]), np.uint8).reshape(m["height"], m["width"])
    cs = m["cell_size"]
    rows, cols = np.nonzero(a >= occ)
    xs, ys = m["max_x"] - (rows + .5) * cs, m["max_y"] - (cols + .5) * cs
    dx, dy = xs - p["x"], ys - p["y"]
    fx = dx * math.cos(p["theta"]) + dy * math.sin(p["theta"])
    ly = -dx * math.sin(p["theta"]) + dy * math.cos(p["theta"])
    sel = (fx > 0) & (abs(ly) < half)
    if not sel.any():
        return None, None
    i = np.argmin(np.where(sel, fx, 99))
    # side check: nearest cell in the corridor, and the angle of the strongest wall line ahead
    return float(fx[i] - BODY_R), float(ly[i])


def main():
    speed = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    dist = float(sys.argv[2]) if len(sys.argv) > 2 else 1.2
    m = get("/api/map")
    p0 = get("/api/pose")["pose"]
    g0 = front_gap(m, p0)
    print(f"before: pose {p0['x']:.3f},{p0['y']:.3f} heading {math.degrees(p0['theta']):.1f} deg; map gap ahead {g0[0]:.2f} m" if g0[0] is not None else "before: nothing ahead on the map")
    subprocess.run([sys.executable, str(ROOT / "tools" / "drive_test.py"), "--manual", "wait:2",
                    f"move:{speed},{dist}", f"wait:{dist / (speed * 0.025) + 2:.1f}", "stop"], capture_output=True)
    time.sleep(1.5)
    p1 = get("/api/pose")["pose"]
    g1 = front_gap(m, p1)
    moved = math.hypot(p1["x"] - p0["x"], p1["y"] - p0["y"])
    print(f"after:  pose {p1['x']:.3f},{p1['y']:.3f} heading {math.degrees(p1['theta']):.1f} deg; moved {moved:.2f} m")
    print(f"map gap ahead now: {g1[0]:.2f} m (cell at {g1[1]:+.2f} m to the side)" if g1[0] is not None else "map: nothing ahead")
    sys.path.insert(0, str(ROOT))
    import lucy_live
    log = lucy_live.ssh_run("grep -E 'MOVE|status:[2-9]' /data/user/app/log/sensor_node.ERROR | tail -4 | cut -c1-120")
    print("sensor log (status 4 = stopped early, e.g. bumper):")
    print((log or b"").decode(errors="replace"))


if __name__ == "__main__":
    main()
