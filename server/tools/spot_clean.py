"""Spot clean (spiral) where Lucy currently is. Needs her off the dock.

    python spot_clean.py [seconds]     # default 120

How it works (found 2026-10-14): rx-channel messages are routed by their "key" field,
not the cmd name. key 13 = spiral ("planning spiral."), key 12 = A2B go-to-point,
key 14 = voice talk. Spiral runs as a manual-control sub-mode, so manual mode must be
on (MANCTRL S) and kept alive with MANCTRL K every few seconds, or it times out after
~14s. When this script stops sending K she times out and pauses; send "dock" to go home.
"""
import json
import sys
import time
import urllib.request

API = "http://127.0.0.1:8080/api/rxcmd"


def rx(cmd, data="", key="2"):
    body = json.dumps({"cmd": cmd, "data": data, "key": key, "wait": 0}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 120
rx("MANCTRL", "S")
time.sleep(2)
rx("SPIRAL", "", key="13")
end = time.time() + seconds
while time.time() < end:
    time.sleep(3)
    rx("MANCTRL", "K")
print("done; she'll time out in ~14s. Send 'python lucy_control.py raw dock' to send her home.")
