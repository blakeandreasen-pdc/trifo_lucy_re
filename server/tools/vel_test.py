r"""Send direct wheel-velocity commands to Lucy (ZeroMQ into sensor_node, see drive_proto.py),
holding manual mode open (MANCTRL S + K every 3 s) so guidance stays out of the way.
    python tools\vel_test.py "L,R,ms[,pause_s]" ["L,R,ms" ...] [--dock] [--no-start]
e.g.  python tools\vel_test.py 10,10,1000,3 -10,-10,1000
Units: whatever her driver uses ("nominal speed"; guidance backs off the dock at 4.0)."""
import json
import subprocess
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


def send(payloads):
    """One SSH call, one zq run per (id, ServiceMsg bytes); zq adds the RPC wrapper with her
    own boot-clock timestamp (never build timestamps here - see zq.c)."""
    script = "".join(f"{ZQ} {MOTION} DEALER @{i}:{p.hex()} 200\n" for i, p in payloads)
    for _ in range(3):
        out = lucy_live.ssh_run(script, timeout=30)
        if out:
            return out.decode(errors="replace")
    return "(ssh failed)"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    stop = threading.Event()

    def keepalive():
        while not stop.wait(3):
            rx("MANCTRL", "K")

    if "--no-start" not in sys.argv:
        rx("MANCTRL", "S")
        time.sleep(4)                 # on the dock she backs off ~35 cm first
        rx("MANCTRL", "ANGLE:0")
    threading.Thread(target=keepalive, daemon=True).start()
    rid = int(time.time()) % 100000 * 10
    for i, a in enumerate(args):
        p = [float(v) for v in a.split(",")]
        left, right, ms = p[0], p[1], int(p[2])
        pause = p[3] if len(p) > 3 else ms / 1000 + 1
        print(f"velocity {left} {right} for {ms} ms")
        print(send([(rid + i, D.velocity(left, right, ms, rid + i))]).strip().splitlines()[-1])
        time.sleep(pause)
    stop.set()
    if "--dock" in sys.argv:
        rx("MANCTRL", "E")
        time.sleep(1.5)
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8090/api/speaker", data=b'{"value":"dock"}'), timeout=5).read()
        print("docking")
    else:
        print("still in manual mode - it times out ~14 s after the last keepalive (then send dock)")


if __name__ == "__main__":
    main()
