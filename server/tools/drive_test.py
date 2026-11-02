r"""Send a sequence of motion commands to Lucy's wheels (ZeroMQ into sensor_node, the same
commands guidance uses; see drive_proto.py). The whole sequence runs on the robot in one go.
    python tools\drive_test.py STEP [STEP ...] [--manual]
Steps:  move:SPEED,DIST       straight forward (guidance: speed 4-8, dist 1000 = keep going)
        back:SPEED,DIST       straight backward (direction guess)
        rot:LEFT,RIGHT[,TARGET]  wheel speeds; TARGET heading rad, default 1000 = no target
        vel:LEFT,RIGHT,TIME   velocity command (maintain time; units being worked out)
        pose:SPEED,X,Y        target_pose (robot-relative?)
        stop                  stop
        wait:SECONDS
--manual: put her in manual mode first (MANCTRL S, ANGLE:0) and keep it alive.
e.g.  python tools\drive_test.py move:6,0.3 wait:3 rot:6,-6 wait:1.5 stop"""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import drive_proto as D  # noqa: E402
import lucy_live  # noqa: E402

ZQ = "/data/lucy_local/zq"
MOTION = "/data/local/tmp/TrifoIPC_planning_actor-motion_command_REQ"


def rx(cmd, data, key="2"):
    req = urllib.request.Request("http://127.0.0.1:8090/api/rx", data=json.dumps(
        {"cmd": cmd, "data": data, "key": key}).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).read()


def build(steps, base):
    lines = []
    for i, s in enumerate(steps):
        kind, _, arg = s.partition(":")
        v = [float(x) for x in arg.split(",")] if arg else []
        cid = base + i
        if kind == "wait":
            lines.append(f"sleep {v[0]}")
            continue
        if kind == "move":
            p = D.move(3, v[0], v[1], cid)
        elif kind == "back":
            p = D.move(4, v[0], v[1], cid)
        elif kind == "rot":
            p = D.rotate(v[0], v[1], v[2] if len(v) > 2 else 1000.0, cid)
        elif kind == "vel":
            p = D.velocity(v[0], v[1], v[2], cid)
        elif kind == "pose":
            p = D.target_pose(v[0], v[1], v[2], cid)
        elif kind == "stop":
            p = D.stop(cid)
        else:
            raise SystemExit(f"unknown step {s}")
        lines.append(f"echo '> {s}'; {ZQ} {MOTION} DEALER @{cid}:{p.hex()} 30 | tail -1")
    return "\n".join(lines) + "\n"


def main():
    steps = [a for a in sys.argv[1:] if not a.startswith("--")]
    stop = threading.Event()
    if "--manual" in sys.argv:
        rx("MANCTRL", "S")
        time.sleep(1)
        rx("MANCTRL", "ANGLE:0")

        def keepalive():
            while not stop.wait(3):
                rx("MANCTRL", "K")
        threading.Thread(target=keepalive, daemon=True).start()
    base = int(time.time()) % 100000 * 10
    out = lucy_live.ssh_run(build(steps, base), timeout=120)
    print(out.decode(errors="replace") if out else "(ssh failed)")
    stop.set()


if __name__ == "__main__":
    main()
