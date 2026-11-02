import math, time, goto
goto.start_manual()
print("arrived" if goto.drive_to(2.25, 0.5, timeout=90, tol=0.2) else "timeout", goto.pose(), flush=True)
x, y = goto.pose()
h = math.atan2(0.85 - y, 1.5 - x)          # face the white object
tx, ty = round(x + 0.25*math.cos(h), 2), round(y + 0.25*math.sin(h), 2)
print("hop to", tx, ty, "heading", round(math.degrees(h)), flush=True)
goto.drive_to(tx, ty, timeout=30, tol=0.1)
time.sleep(1.5)
print("photo:", goto.photo("obj_front"), flush=True)
goto.rx("MANCTRL", "K")
