"""Drive Lucy to a map point with A2B (rx key 12, data "x,y"), keeping manual mode alive
and logging her pose so the units/frame can be checked.

    python a2b_test.py <x> <y> [seconds] [--backout]
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
import map_reader  # noqa: E402

API = "http://127.0.0.1:8080/api/rxcmd"


def rx(cmd, data="", key="2"):
    body = json.dumps({"cmd": cmd, "data": data, "key": key, "wait": 0}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def pose():
    m = map_reader.get_live_map(force=True)
    p = m.get("pose") or {}
    return f"x={p.get('x', float('nan')):.2f} y={p.get('y', float('nan')):.2f}"


x, y = sys.argv[1], sys.argv[2]
seconds = float(sys.argv[3]) if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else 40
print("start", time.strftime("%H:%M:%S"), pose(), flush=True)
rx("MANCTRL", "S")
time.sleep(2)
if "--backout" in sys.argv:
    end = time.time() + 2.5
    while time.time() < end:
        rx("MANCTRL", "ANGLE:8")
        time.sleep(0.8)
    rx("MANCTRL", "ANGLE:0")
    time.sleep(1.5)
    print("backed out", pose(), flush=True)
rx("A2B", f"{x},{y}", key="12")
end = time.time() + seconds
while time.time() < end:
    time.sleep(3)
    rx("MANCTRL", "K")
    print(time.strftime("%H:%M:%S"), pose(), flush=True)
print("done")
