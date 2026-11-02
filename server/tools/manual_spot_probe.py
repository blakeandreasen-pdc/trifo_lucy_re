"""Enter manual mode, back off the dock, then try candidate spot-clean commands
while keeping manual mode alive. Prints UTC send times to match against Lucy's logs.

    python manual_spot_probe.py
"""
import json
import time
import urllib.request
from datetime import datetime, timezone

API = "http://127.0.0.1:8080/api/rxcmd"


def rx(cmd, data="", wait=0):
    body = json.dumps({"cmd": cmd, "data": data, "wait": wait}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as e:
        r = {"error": str(e)}
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"{stamp} {cmd} {data!r} -> {'ok' if r.get('ok') else r}", flush=True)
    return r


def hold(seconds, data="ANGLE:0"):
    """Keep manual mode alive with joystick-centre pings."""
    end = time.time() + seconds
    while time.time() < end:
        rx("MANCTRL", data)
        time.sleep(1.5)


rx("MANCTRL", "S")
time.sleep(2)
hold(2.5, "ANGLE:8")      # reverse off the dock
hold(2)                   # stop

candidates = [("SPOT", ""), ("SPIRAL", ""), ("MANCTRL", "SPIRAL")]
candidates += [(str(n), "") for n in range(1, 13)]
for cmd, data in candidates:
    rx(cmd, data)
    hold(4)

rx("MANCTRL", "E")
