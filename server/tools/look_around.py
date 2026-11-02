"""Drive to a place, then turn on the spot in pulses taking a photo at each heading.

    python look_around.py <place|x,y> [--dock]

Photos go to captures/look_<HHMMSS>/ named by heading in degrees (map frame).
"""
import math
import os
import sys
import time

import goto
from goto import rx, pose, PLACES


def heading():
    import map_reader
    p = map_reader.get_live_map(force=True).get("pose") or {}
    return p.get("theta")


def main():
    target = sys.argv[1]
    tx, ty = PLACES[target] if target in PLACES else map(float, target.split(","))
    out = os.path.join(goto.BASE, "captures", f"look_{time.strftime('%H%M%S')}")
    os.makedirs(out, exist_ok=True)
    goto.start_manual()
    print("arrived" if goto.drive_to(tx, ty) else "timeout", pose(), flush=True)

    turned, last = 0.0, heading()
    while turned < 2 * math.pi and last is not None:
        rx("MANCTRL", "ANGLE:1")
        time.sleep(0.15)
        rx("MANCTRL", "ANGLE:0")
        time.sleep(1.5)                       # settle so the frame isn't blurred
        th = heading()
        if th is None:
            break
        turned += abs(math.atan2(math.sin(th - last), math.cos(th - last)))
        last = th
        frame = goto.lucy_live.grab_camera_frame()
        if frame:
            name = f"h{int(math.degrees(th)) % 360:03d}.png"
            with open(os.path.join(out, name), "wb") as f:
                f.write(goto.lucy_live.nv12_to_png(frame["nv12"], 2))
            print(f"photo {name} (turned {math.degrees(turned):.0f} deg)", flush=True)
        rx("MANCTRL", "K")
    print("saved to", out, flush=True)
    if "--dock" in sys.argv:
        goto.dock()


if __name__ == "__main__":
    main()
