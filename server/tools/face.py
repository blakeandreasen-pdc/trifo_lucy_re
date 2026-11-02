"""Point Lucy's camera at a map heading by driving a short hop in that direction, then
take a photo. (Spinning in manual mode turns ~165 deg minimum, so it can't aim finely.)

    python face.py <heading_deg> [hop_m]      # heading in map frame, e.g. 220
"""
import math
import sys
import time

import goto

h = math.radians(float(sys.argv[1]))
hop = float(sys.argv[2]) if len(sys.argv) > 2 else 0.35
goto.start_manual()
x, y = goto.pose()
tx, ty = round(x + hop * math.cos(h), 2), round(y + hop * math.sin(h), 2)
print(f"from ({x:.2f}, {y:.2f}) hop to ({tx}, {ty})", flush=True)
goto.drive_to(tx, ty, timeout=40, tol=0.12)
time.sleep(1.5)
print("photo:", goto.photo(f"face{int(float(sys.argv[1]))}"), flush=True)
goto.rx("MANCTRL", "K")
