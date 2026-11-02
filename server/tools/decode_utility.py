r"""List utility commands (brushes, fan, voice, lights: ServiceMsg field 5) that sensor_node received
in a strace capture from tools/motion_capture.sh.
    python tools\decode_utility.py [capture.txt]    (default: fetch /data/lucy_local/motion_strace.txt)"""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lucy_live  # noqa: E402
from decode_motion import fields, unesc  # noqa: E402


def main():
    if len(sys.argv) > 1 and sys.argv[1] != "--all":
        txt = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    else:
        cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [lucy_live.SSH_HOST, "cat /data/lucy_local/motion_strace.txt"]
        txt = subprocess.run(cmd, capture_output=True, timeout=60).stdout.decode(errors="replace")
    for line in txt.splitlines():
        m = re.search(r'(\d\d:\d\d:\d\d\.\d+) .*recvfrom\((\d+), "((?:\\x[0-9a-f]{2})+)"', line)
        if not m:
            continue
        b = unesc(m.group(3))[2:]
        if "--all" in sys.argv and len(b) > 16:
            print(m.group(1), "fd", m.group(2), b.hex())
            continue
        try:
            top = dict(fields(b))
            pay = top.get(8)
            if not isinstance(pay, bytes):
                continue
            for f, v in fields(pay):
                if f == 5 and isinstance(v, bytes):
                    print(m.group(1), "fd", m.group(2), "utility", v.hex(), fields(v))
        except Exception:
            continue


if __name__ == "__main__":
    main()
