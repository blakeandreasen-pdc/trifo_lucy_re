r"""Decode the motion commands sensor_node received in a strace capture (tools/motion_capture.sh):
    python tools\decode_motion.py [capture.txt]     (default: fetch /data/lucy_local/motion_strace.txt)
Prints one line per command: time, kind and fields (move / rotate / stop / velocity / ...)."""
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lucy_live  # noqa: E402

KINDS = {1: "move", 2: "rotate", 3: "wall_follow", 4: "stop", 5: "dock", 6: "target_pose", 7: "velocity"}


def fields(b):
    i, out = 0, []
    while i < len(b):
        key, i = varint(b, i)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, i = varint(b, i)
        elif wt == 5:
            v = round(struct.unpack("<f", b[i:i + 4])[0], 4)
            i += 4
        elif wt == 1:
            v = struct.unpack("<d", b[i:i + 8])[0]
            i += 8
        elif wt == 2:
            n, i = varint(b, i)
            v = b[i:i + n]
            i += n
        else:
            raise ValueError
        out.append((f, v))
    return out


def varint(b, i):
    v = s = 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7f) << s
        s += 7
        if c < 0x80:
            return v, i


def unesc(s):
    return bytes(int(h, 16) for h in re.findall(r"\\x([0-9a-f]{2})", s))


def main():
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(errors="replace")
    else:
        text = lucy_live.ssh_run("cat /data/lucy_local/motion_strace.txt", timeout=60).decode(errors="replace")
    for line in text.splitlines():
        m = re.search(r'(\d\d:\d\d:\d\d\.\d+) .*recvfrom.*?"((?:\\x[0-9a-f]{2})+)"', line)
        if not m:
            continue
        b = unesc(m.group(2))[2:]           # drop the ZMTP frame header
        try:
            rpc = dict(fields(b))
            svc = rpc.get(8)
            if not svc:
                continue
            for f, item in fields(svc):
                if f != 4:
                    print(m.group(1), f"service field {f}: {item.hex() if isinstance(item, bytes) else item}")
                    continue
                for k, body in fields(item):
                    print(m.group(1), KINDS.get(k, k), fields(body) if isinstance(body, bytes) else body)
        except (ValueError, IndexError, struct.error):
            pass


if __name__ == "__main__":
    main()
