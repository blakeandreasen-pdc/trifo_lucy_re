"""Measure how far Lucy turns for different MANCTRL turn commands (she must be off-dock)."""
import math
import time

import goto
from goto import rx
from look_around import heading

goto.start_manual()
for data in ["ANGLE:2", "ANGLE:3", "ANGLE:5", "ANGLE:6", "ANGLE:7", "ANGLE:9", "ANGLE:10", "ANGLE:11", "ANGLE:12"]:
    before = heading(); p0 = goto.pose()
    rx("MANCTRL", data)
    time.sleep(0.3)
    rx("MANCTRL", "ANGLE:0")
    time.sleep(2)
    after = heading()
    d = math.degrees(math.atan2(math.sin(after - before), math.cos(after - before)))
    p1 = goto.pose(); print(f"{data:12s} turned {d:+.0f} deg, moved {math.hypot(p1[0]-p0[0], p1[1]-p0[1]):.2f} m", flush=True)
    rx("MANCTRL", "K")
