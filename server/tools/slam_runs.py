"""Summarise Lucy's runs from her slam log: one block per run with how steady her localisation was.

    python tools/slam_runs.py [--since "1024 21:00"] [--file local_copy.txt]

Pulls /data/user/app/log/slam_node.INFO over SSH (or reads --file), splits it into runs at each
WORKING.CLEAN.* state, and per run reports: start/end, the states it went through, relocalisations,
map saves (and the file name), and the jitter of "update latest transform" (her map<-odom
correction): median / 90th percentile / max step in metres, and heading steps in degrees.
The transform angle is in radians and not wrapped, so jumps of 2*pi (the "6.3" flips) are the same
heading written differently: they are wrapped away here."""
import argparse
import math
import os
import re
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lucy_live  # noqa: E402

LOG = "/data/user/app/log/slam_node.INFO"
HEAD = re.compile(r"^[IWEF](\d{4}) (\d\d:\d\d:\d\d)\.\d+\s+\d+ (\S+)\] (.*)")
TF = re.compile(r"update latest transform = \[\[([-\d.e]+), ([-\d.e]+)\], ([-\d.e]+)\]")


def fetch():
    cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [lucy_live.SSH_HOST, f"cat {LOG}"]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300).stdout


def entries(text):
    """-> (mmdd, hh:mm:ss, src, msg) per log entry (continuation lines dropped)."""
    for line in text.splitlines():
        m = HEAD.match(line)
        if m:
            yield m.groups()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help='e.g. "1024 21:00"')
    ap.add_argument("--file")
    a = ap.parse_args()
    text = open(a.file, encoding="utf-8", errors="replace").read() if a.file else fetch()
    runs, cur = [], None
    for day, t, src, msg in entries(text):
        if f"{day} {t}" < a.since:
            continue
        st = re.search(r"current_state_=(\S+)", msg)
        if st:
            s = st.group(1)
            starts = s in ("WORKING.CLEAN.TRACK_AGAINST_MAP", "WORKING.CLEAN.NEW_CLEAN")
            if starts and cur and not cur["ended"]:      # docked and set off again without idling
                cur["ended"], cur["end"] = True, f"{day} {t}"
            if starts or (s.startswith("WORKING.CLEAN.") and (cur is None or cur["ended"])):
                cur = {"start": f"{day} {t}", "states": [], "tf": [], "reloc": 0, "lost": 0,
                       "saves": [], "ended": False, "end": None}
                runs.append(cur)
            if cur and not cur["ended"]:
                if not cur["states"] or cur["states"][-1] != s:
                    cur["states"].append(f"{s.replace('WORKING.', '')} {t[:5]}")
                if s.startswith("WORKING.IDLE"):
                    cur["ended"], cur["end"] = True, f"{day} {t}"
            continue
        if cur is None:
            continue
        if "Map saved to" in msg:
            cur["saves"].append(f"{t} {msg.split('Map saved to')[1].strip()}")
        if cur["ended"]:
            continue
        m = TF.search(msg)
        if m:
            cur["tf"].append((t, float(m.group(1)), float(m.group(2)), float(m.group(3))))
        elif "PERCEPTION_RELOCALIZE_SUCCEEDED" in msg:
            cur["reloc"] += 1
        elif "status = 2" in msg and "Updated charger" not in msg:
            cur["lost"] += 1
    for r in runs:
        print(f"== run {r['start']} -> {r['end'] or '(still going)'}")
        print("   states:", " > ".join(r["states"]))
        print(f"   relocalised {r['reloc']}x, LOST reports {r['lost']}, saves: {r['saves'] or 'none'}")
        tf = r["tf"]
        if len(tf) < 3:
            print("   too few transform updates")
            continue
        dd, da, big = [], [], []
        for (t0, x0, y0, a0), (t1, x1, y1, a1) in zip(tf, tf[1:]):
            d = math.hypot(x1 - x0, y1 - y0)
            th = math.degrees(math.atan2(math.sin(a1 - a0), math.cos(a1 - a0)))
            dd.append(d)
            da.append(abs(th))
            if d > 0.15 or abs(th) > 3:
                big.append(f"{t1} {d:.2f}m {th:+.1f}deg")
        dd.sort()
        da.sort()
        q = lambda v, p: v[min(len(v) - 1, int(p * len(v)))]
        print(f"   {len(tf)} corrections: step median {statistics.median(dd):.3f} m, p90 {q(dd, .9):.3f} m, "
              f"max {dd[-1]:.2f} m; heading median {statistics.median(da):.1f} deg, p90 {q(da, .9):.1f}, "
              f"max {da[-1]:.1f}")
        if big:
            print(f"   big steps ({len(big)}):", ", ".join(big[:12]), "..." if len(big) > 12 else "")


if __name__ == "__main__":
    main()
