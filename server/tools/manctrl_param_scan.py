"""Find which MANCTRL data values Lucy accepts. Rejected ones are logged by cloud_node as
"manual control param error:<value>", so accepted = sent minus logged. Sends ANGLE:0
(stop) after every candidate to keep manual mode alive and halt any motion.

    python manctrl_param_scan.py
"""
import json
import string
import time
import urllib.request
from datetime import datetime, timezone

API = "http://127.0.0.1:8080/api/rxcmd"


def rx(cmd, data=""):
    body = json.dumps({"cmd": cmd, "data": data, "wait": 0}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


words = ["SPOT", "Spot", "spot", "SPIRAL_CLEAN", "spiral", "SPOT_CLEAN", "A2B", "A2B:0.5:0.5",
         "A2B:0.5,0.5", "BLOWER", "DOCK", "HOME", "CAMERA", "LIGHT", "TALK", "SPEED:4"]
candidates = list(string.ascii_uppercase) + list(string.ascii_lowercase) + words
print("start", datetime.now(timezone.utc).strftime("%H:%M:%S"), flush=True)
rx("MANCTRL", "S")
time.sleep(2)
for c in candidates:
    if c in ("S", "E"):          # already known: enter/exit manual
        continue
    rx("MANCTRL", c)
    time.sleep(0.8)
    rx("MANCTRL", "ANGLE:0")
    time.sleep(0.8)
rx("MANCTRL", "E")
print("end", datetime.now(timezone.utc).strftime("%H:%M:%S"), flush=True)
print("SENT", json.dumps([c for c in candidates if c not in ("S", "E")]))
