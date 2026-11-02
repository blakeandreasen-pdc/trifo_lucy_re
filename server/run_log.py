"""Run log: one entry per clean, built from Lucy's own records and logs (2026-10-26).

    python run_log.py            (print the log; refreshes from her first)

Sources, all read over one SSH call:
  - data.db tb_detail: her own row per clean (area m2, duration s, end time). This decides what
    counts as a run. (Its .ogm map file is NOT read: decoding those was dropped at Chloe's request.)
  - manager_node.INFO "add new signal": how it was started and how it ended.
  - slam_node.INFO: mapping run or clean on the saved map, relocalisations, map saves and how much
    her map<-odom correction jumped (the same numbers as tools/slam_runs.py).
  - sensor_node.INFO: named problems ("Robot Exception: BUMPER_STUCK" ...) and battery
    ("charging_status:... voltage:NN" is her battery %, logged every 10 s).
Her logs start again when she reboots, so finished entries are kept in runlog.json and never
rebuilt from thinner data."""
import datetime as dt
import json
import math
import os
import re
import statistics
import threading
import time

import lucy_live

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "runlog.json")
REFRESH_S = 300
_lock = threading.Lock()

PROBE = r"""cd /data/user/app
echo "#DETAIL"; sqlite3 data.db "select id,area,duration,uptime from tb_detail order by id desc limit 80"
cd log
echo; echo "#SIG"; grep -h "add new signal" manager_node.INFO | busybox awk '{print $1, substr($2,1,8), $NF}'
echo; echo "#SLAM"; grep -h -E "current_state_=|update latest transform|RELOCALIZE_SUCCEEDED|Map saved to|status = 2" slam_node.INFO
echo; echo "#SENS"; grep -h -E "Robot Exception|charging_status" sensor_node.INFO | grep -v Resume | busybox awk '
  /charging_status/ { k=$1" "substr($2,1,5); if (k!=pb) print $1, substr($2,1,8), "BAT", $6; pb=k; next }
  { k=$1" "substr($2,1,5)" "$NF; if (k!=pe) print $1, substr($2,1,8), "EXC", $NF; pe=k }'
echo; echo "#END"
"""
TF = re.compile(r"update latest transform = \[\[([-\d.e]+), ([-\d.e]+)\], ([-\d.e]+)\]")
NICE = {"WHEEL_NOT_ON_SURFACE": "wheel lifted", "BUMPER_STUCK": "bumper stuck", "DUSTBIN_MISSING": "bin out",
        "CLIFF": "cliff sensor", "WHEEL_STUCK": "wheel stuck", "SIDE_BRUSH_STUCK": "side brush stuck",
        "MAIN_BRUSH_STUCK": "main brush stuck"}


def _when(tag, hms, now):
    """'E1026', '07:29:18' -> datetime (her log lines carry no year)."""
    t = dt.datetime(now.year, int(tag[1:3]), int(tag[3:5]), *map(int, hms[:8].split(":")))
    return t.replace(year=now.year - 1) if t > now + dt.timedelta(days=1) else t


def fetch():
    out = lucy_live.ssh_run(PROBE, timeout=120)
    if not out or b"#END" not in out:
        raise RuntimeError("couldn't read her logs")
    return out.decode(errors="replace")


def parse(text, now=None):
    now = now or dt.datetime.now()
    sec, detail, sig, slam, bat, exc = None, [], [], [], [], []
    for line in text.splitlines():
        if line.startswith("#"):
            sec = line[1:]
            continue
        if sec == "DETAIL":
            p = line.split("|")
            if len(p) == 4 and p[3].isdigit():
                detail.append((int(p[0]), float(p[1] or 0), int(p[2] or 0), dt.datetime.fromtimestamp(int(p[3]))))
        elif sec == "SIG":
            p = line.split()
            if len(p) == 3:
                sig.append((_when(p[0], p[1], now), p[2]))
        elif sec == "SLAM":
            m = re.match(r"^([IWEF]\d{4}) (\d\d:\d\d:\d\d)", line)
            if m:
                slam.append((_when(m.group(1), m.group(2), now), line))
        elif sec == "SENS":
            p = line.split()
            if len(p) == 4 and p[2] == "BAT" and p[3].startswith("voltage:"):
                bat.append((_when(p[0], p[1], now), int(p[3][8:])))
            elif len(p) == 4 and p[2] == "EXC":
                exc.append((_when(p[0], p[1], now), p[3]))
    detail.sort(key=lambda r: r[3])
    first_log = min([t for t, _ in slam] or [now])
    runs = []
    for i, (rid, area, dur, end) in enumerate(detail):
        prev_end = detail[i - 1][3] if i else end - dt.timedelta(seconds=dur + 7200)
        lo, hi = prev_end + dt.timedelta(seconds=5), end + dt.timedelta(seconds=90)
        nominal = end - dt.timedelta(seconds=dur)
        r = {"id": rid, "end": end.isoformat(timespec="seconds"), "minutes": round(dur / 60, 1),
             "area_m2": round(area, 1), "logs": end > first_log}
        # start: the last start signal before her counted time began (pauses can make it earlier)
        starts = [(t, s) for t, s in sig if lo <= t <= nominal + dt.timedelta(seconds=120)
                  and s in ("CLOUD_START_CLEAN", "DRIVER_START_CLEAN")]
        start = starts[-1][0] if starts else nominal
        r["start"] = start.isoformat(timespec="seconds")
        r["started_by"] = {"CLOUD_START_CLEAN": "page or schedule", "DRIVER_START_CLEAN": "her button"}.get(
            starts[-1][1]) if starts else None
        win = lambda rows: [x for x in rows if start - dt.timedelta(seconds=5) <= x[0] <= hi]
        ends = [s for t, s in win(sig) if s in ("GUIDANCE_CLEAN_FINISHED", "CLOUD_START_DOCK", "DRIVER_START_DOCK", "CLOUD_PAUSE")]
        r["ended"] = {"GUIDANCE_CLEAN_FINISHED": "finished", "CLOUD_START_DOCK": "sent home",
                      "DRIVER_START_DOCK": "home button", "CLOUD_PAUSE": "paused"}.get(ends[-1]) if ends else None
        b = win(bat)
        r["battery"] = [b[0][1], b[-1][1], min(v for _, v in b)] if b else None
        probs = {}
        for _, name in win(exc):
            name = NICE.get(name, name.lower().replace("_", " "))
            probs[name] = probs.get(name, 0) + 1
        r["problems"] = probs
        states, tf, reloc, lost, save = [], [], 0, 0, None
        for t, line in win(slam):
            st = re.search(r"current_state_=(\S+)", line)
            if st:
                if not states or states[-1] != st.group(1):
                    states.append(st.group(1))
                continue
            m = TF.search(line)
            if m:
                tf.append((t, float(m.group(1)), float(m.group(2)), float(m.group(3))))
            elif "RELOCALIZE_SUCCEEDED" in line:
                reloc += 1
            elif "Map saved to" in line:
                save = line.split("Map saved to")[1].strip()
            elif "status = 2" in line and "Updated charger" not in line:
                lost += 1
        r["kind"] = ("mapping run" if any(s.endswith("NEW_CLEAN") for s in states)
                     else "clean on saved map" if any("TRACK_AGAINST_MAP" in s for s in states) else None)
        r["error_stops"] = sum(1 for s in states if s.startswith("SPECIAL.ERROR"))
        r["relocalised"], r["lost"] = reloc, lost
        r["map_saved"] = None if not save else ("main map" if save.endswith("pose_graph_map.pbstream")
                                                else "map100 copy" if "map100" in save else save)
        if len(tf) >= 3:
            steps = []
            for (t0, x0, y0, a0), (t1, x1, y1, a1) in zip(tf, tf[1:]):
                d = math.hypot(x1 - x0, y1 - y0)
                th = math.degrees(math.atan2(math.sin(a1 - a0), math.cos(a1 - a0)))
                steps.append((d, th, t1))
            big = [s for s in steps if s[0] > 0.5 or abs(s[1]) > 10]
            worst = max(steps, key=lambda s: s[0])
            r["steadiness"] = {"median_cm": round(statistics.median(s[0] for s in steps) * 100, 1),
                               "jumps": len(big), "worst_m": round(worst[0], 2), "worst_deg": round(worst[1], 1),
                               "worst_at": worst[2].strftime("%H:%M:%S")}
        else:
            r["steadiness"] = None
        runs.append(r)
    return runs


def _load():
    try:
        return json.load(open(CACHE, encoding="utf-8"))
    except Exception:
        return {"runs": {}, "at": 0}


_state = {"busy": False, "error": None}


def refresh():
    """Re-read her logs into runlog.json (~15 s: her sensor log is big)."""
    with _lock:
        c = _load()
        err = None
        try:
            for r in parse(fetch()):
                old = c["runs"].get(str(r["id"]))
                if old and old.get("logs") and not r["logs"]:
                    continue                       # her logs have rolled over: keep what we had
                c["runs"][str(r["id"])] = r
            c["at"] = time.time()
            tmp = CACHE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(c, f, indent=1)
            os.replace(tmp, CACHE)
        except Exception as e:
            err = str(e)[:200]
        _state["error"] = err


def _bg():
    try:
        refresh()
    finally:
        _state["busy"] = False


def get(force=False, limit=None):
    """-> {"runs": [newest first], "at", "error", "refreshing"}. Answers from the cache at once; if
    it's over 5 minutes old (or force), a refresh starts in the background and the page asks again."""
    c = _load()
    if (force or time.time() - c.get("at", 0) > REFRESH_S) and not _state["busy"]:
        _state["busy"] = True
        threading.Thread(target=_bg, daemon=True).start()
    runs = sorted(c["runs"].values(), key=lambda r: r["end"], reverse=True)
    return {"runs": runs[:limit] if limit else runs, "total": len(runs), "at": c.get("at", 0),
            "error": _state["error"], "refreshing": _state["busy"]}


if __name__ == "__main__":
    refresh()
    d = get()
    if d["error"]:
        print("error:", d["error"])
    for r in d["runs"][:25]:
        b = r["battery"]
        print(f"{r['start'][5:16]}  {r['minutes']:5} min  {r['area_m2']:5} m2  {r['kind'] or '?':18} "
              f"{r['started_by'] or '?':16} -> {r['ended'] or '?':11} bat {b[0] if b else '?'}->{b[1] if b else '?'}  "
              f"reloc {r['relocalised']}  errs {r['error_stops']} {r['problems'] or ''}  map {r['map_saved']}  "
              f"steady {r['steadiness']}")
