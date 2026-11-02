import time, goto
goto.rx("MANCTRL", "S"); time.sleep(1.5)
p0 = goto.pose()
goto.rx("MANCTRL", "ANGLE:8"); time.sleep(0.3); goto.rx("MANCTRL", "ANGLE:0"); time.sleep(3)
print("moved from", p0, "to", goto.pose())
print("photo:", goto.photo("backed"))
goto.rx("MANCTRL", "K")
