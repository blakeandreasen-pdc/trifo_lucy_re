import math, time, goto
from goto import rx
from look_around import heading
goto.start_manual()
for data, hold in [("ANGLE:7", 1.0), ("ANGLE:7", 2.0), ("ANGLE:1", 1.0)]:
    b = heading()
    end = time.time() + hold
    while time.time() < end:
        rx("MANCTRL", data); time.sleep(0.3)
    rx("MANCTRL", "ANGLE:0"); time.sleep(2)
    a = heading()
    print(data, hold, "s ->", round(math.degrees(math.atan2(math.sin(a-b), math.cos(a-b)))), "deg", flush=True)
    rx("MANCTRL", "K")
