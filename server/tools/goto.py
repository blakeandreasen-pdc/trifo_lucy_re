"""Send Lucy to a named place (or x,y in map metres) and grab a camera frame on arrival.

    python goto.py kitchen            # named place from PLACES
    python goto.py 1.0,0.3            # raw map coordinates (metres, map1 frame)
    python goto.py kitchen --dock     # go, snap a photo, then return to dock

A2B = rx key 12 with data "x,y" (map metres). It only runs in manual mode, which must be
kept alive with MANCTRL K. A pending A2B fires the next time manual mode starts, so we send
ANGLE:0 right after entering manual mode to clear it.
"""
import json
import math
import os
import socket
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import lucy_live  # noqa: E402
import map_reader  # noqa: E402

API = "http://127.0.0.1:8080/api/rxcmd"

# Rough map1 positions, from camera frames matched to poses on 2026-10-14.
PLACES = {
    # your own rough map coordinates, in metres. These are examples.
    "dock": (0.0, 0.0),
    "kitchen": (2.0, 1.3),
}
# Layout (from the user): lounge (dock under sofa) opens to the kitchen; a door leads to the
# hallway with the bathroom (west end) and three bedrooms; another lounge door goes to a
# second hallway and the front door.


def rx(cmd, data="", key="2"):
    body = json.dumps({"cmd": cmd, "data": data, "key": key, "wait": 0}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def pose():
    p = map_reader.get_live_map(force=True).get("pose") or {}
    return p.get("x"), p.get("y")


def start_manual():
    """Enter manual mode, clear any queued A2B, and reverse off the dock if on it."""
    rx("MANCTRL", "S")
    time.sleep(2)
    rx("MANCTRL", "ANGLE:0")          # clear any queued A2B
    time.sleep(1)
    x, y = pose()
    if x is not None and math.hypot(x - PLACES["dock"][0], y - PLACES["dock"][1]) < 0.35:
        end = time.time() + 2.5       # reverse out from under the sofa
        while time.time() < end:
            rx("MANCTRL", "ANGLE:8")
            time.sleep(0.8)
        rx("MANCTRL", "ANGLE:0")
        time.sleep(1.5)


def drive_to(tx, ty, timeout=120, tol=0.3):
    """A2B to (tx, ty) with keepalives; returns True on arrival. Manual mode must be on."""
    rx("A2B", f"{tx},{ty}", key="12")
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        rx("MANCTRL", "K")
        x, y = pose()
        d = math.hypot(x - tx, y - ty) if x is not None else float("nan")
        print(f"{time.strftime('%H:%M:%S')} at ({x:.2f}, {y:.2f}) dist {d:.2f} m", flush=True)
        if d < tol:
            return True
    return False


def photo(name):
    frame = lucy_live.grab_camera_frame()
    if not frame:
        return None
    out = os.path.join(BASE, "captures", f"{name}_{time.strftime('%H%M%S')}.png")
    with open(out, "wb") as f:
        f.write(lucy_live.nv12_to_png(frame["nv12"], 2))
    return out


def dock():
    rx("MANCTRL", "E")
    time.sleep(2)
    with socket.create_connection(("127.0.0.1", 9999), timeout=10) as s:   # same as lucy_control.py raw dock
        s.sendall(b"2:dock")
        s.recv(4096)
    print("sent dock", flush=True)


def main():
    target = sys.argv[1]
    tx, ty = PLACES[target] if target in PLACES else map(float, target.split(","))
    print(f"going to {target} ({tx}, {ty}); now at {pose()}", flush=True)
    start_manual()
    arrived = drive_to(tx, ty)
    print("photo:", photo(f"goto_{target.replace(',', '_')}"), flush=True)
    print("arrived" if arrived else "gave up (timeout)", flush=True)
    if "--dock" in sys.argv:
        dock()


if __name__ == "__main__":
    main()
