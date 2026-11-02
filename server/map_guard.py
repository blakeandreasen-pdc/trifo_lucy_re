"""Map guard: puts her good map back if a run saves a much smaller one over it.

Why (2026-10-24): a ~30 s resumed run at 21:25 saved a one-submap map over a fresh 19-submap
map, and her next run had to map the house again. She has her own throwaway slot
(pose_graph_map100.pbstream) for aborted runs, but a run that counts as finished saves over the
main map however short it was.

Every minute (one SSH call) it looks at lucy_map/pose_graph_map.pbstream and her slam log:
- a new map file from a *tracking* run (CLEAN.TRACK_AGAINST_MAP) that is under SHRINK x the
  guarded size -> once she's docked/idle, load the guard slot back (tools/map_slots.sh load,
  which first keeps the shrunk map as a "_before_<time>" slot) and log a note;
- anything else is accepted and becomes the new guard: bigger/similar maps after tracking runs,
  any map from a mapping run (CLEAN.NEW_CLEAN, e.g. a new place), and changes with no save in her
  log (a slot loaded from the map page).
Pieces (2026-10-29): runs she doesn't count as finished save to her throwaway
lucy_map/pose_graph_map100.pbstream, which she deletes when the next run starts. That's how a 27 Oct
run that had mapped a bedroom (as "room 2") was lost. Every new map100 is now copied to a slot
"_piece_<time>" (newest PIECE_KEEP kept) so map_merge.py can fold it into the main map.
Backups (2026-10-26): after every new guard, and at least daily, the whole slot folder on Lucy
(/data/lucy_local/maps, ~4 MB packed, _guard = her current map) is copied to map_backups/ here,
newest BACKUP_KEEP kept; so a dead robot doesn't take her maps with it. Restore by unpacking one
into /data/lucy_local/ and loading a slot from the map page.
The guard is the map slot "_guard" on Lucy (/data/lucy_local/maps/_guard); our own bookkeeping is
in map_guard.json next to this file. Started from lucy_stream.py main()."""
import json
import os
import re
import sys
import threading
import time

import lucy_live

SHRINK = 0.7
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map_backups")
BACKUP_KEEP = 10
PIECE_KEEP = 8
BACKUP_EVERY_S = 24 * 3600
EVERY_S = 60
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map_guard.json")
PROBE = r"""cd /data/user/app
stat -c 'FILE %s %Y' lucy_map/pose_graph_map.pbstream 2>/dev/null
stat -c 'M100 %s %Y' lucy_map/pose_graph_map100.pbstream 2>/dev/null
grep -E 'Map saved to \./lucy_map/pose_graph_map\.pbstream' log/slam_node.INFO | tail -1 | sed 's/^/SAVE /'
grep -E 'current_state_=' log/slam_node.INFO | tail -1 | sed 's/^/NOW /'
grep -E 'current_state_=WORKING\.CLEAN\.(NEW_CLEAN|TRACK_AGAINST_MAP)' log/slam_node.INFO | tail -1 | sed 's/^/RUN /'
"""


def _log(msg):
    print(f"[map_guard] {time.strftime('%H:%M:%S')} {msg}", flush=True)


def _notify(text):
    print(f"[notify] {text}", flush=True)     # plug your own messenger in here


class MapGuard:
    def __init__(self, map_slots):
        self.map_slots = map_slots          # lucy_stream.map_slots(mode, name)
        try:
            self.state = json.load(open(STATE, encoding="utf-8"))
        except (OSError, ValueError):
            self.state = {}
        threading.Thread(target=self._run, daemon=True).start()

    def _save_state(self):
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=1)

    def _probe(self):
        out = lucy_live.ssh_run(PROBE, timeout=30)
        if out is None:
            return None
        info = {}
        for line in out.decode(errors="replace").splitlines():
            tag, _, rest = line.partition(" ")
            info[tag] = rest.strip()
        if "FILE" not in info:
            return None
        size, mtime = info["FILE"].split()
        info["size"], info["mtime"] = int(size), int(mtime)
        return info

    def _guard(self, info, why):
        r = self.map_slots("save", "_guard")
        if not r.get("ok"):
            _log(f"couldn't save the guard slot: {r.get('out')}")
            return
        self.state = {"size": info["size"], "mtime": info["mtime"], "save": info.get("SAVE", ""),
                      "at": time.strftime("%Y-%m-%d %H:%M:%S"), "why": why}
        self._save_state()
        _log(f"guarding {info['size']} bytes ({why})")
        self.backup()

    def backup(self):
        """Copy her map slots (tar.gz over SSH) into map_backups/, keep the newest BACKUP_KEEP."""
        import subprocess
        os.makedirs(BACKUP_DIR, exist_ok=True)
        cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [lucy_live.SSH_HOST,
               "cd /data/lucy_local && tar czf - maps"]
        try:
            data = subprocess.run(cmd, capture_output=True, timeout=120).stdout
        except Exception as e:
            _log(f"backup failed: {e}")
            return
        if len(data) < 1000:
            _log("backup failed: nothing came back")
            return
        path = os.path.join(BACKUP_DIR, time.strftime("maps_%Y%m%d_%H%M%S.tar.gz"))
        with open(path, "wb") as f:
            f.write(data)
        for old in sorted(n for n in os.listdir(BACKUP_DIR) if n.startswith("maps_"))[:-BACKUP_KEEP]:
            os.remove(os.path.join(BACKUP_DIR, old))
        self.state["backup_at"] = time.time()
        self._save_state()
        _log(f"backed up her map slots ({len(data) // 1024} KB) to {os.path.basename(path)}")

    def keep_piece(self, info):
        """Copy a new map100 (her throwaway) into a _piece_<time> slot before she deletes it."""
        m = info.get("M100")
        if not m or m == self.state.get("m100"):
            return
        size, mtime = map(int, m.split())
        name = "_piece_" + time.strftime("%Y%m%d_%H%M", time.localtime(mtime))
        keep = PIECE_KEEP
        out = lucy_live.ssh_run(f"""cd /data/lucy_local/maps
mkdir -p {name}
cp /data/user/app/lucy_map/pose_graph_map100.pbstream {name}/pose_graph_map.pbstream && echo COPIED
n=$(ls -d _piece_* | wc -l); [ "$n" -gt {keep} ] && ls -d _piece_* | sort | head -n $((n - {keep})) | while read d; do rm -r "$d"; done
""", timeout=60)
        if out and b"COPIED" in out:
            self.state["m100"] = m
            self._save_state()
            _log(f"kept her throwaway map ({size // 1024} KB) as slot {name}")
        else:
            _log(f"couldn't keep her throwaway map: {out!r}")

    def check(self):
        info = self._probe()
        if info is None:
            return
        self.keep_piece(info)
        st = self.state
        if not st:
            return self._guard(info, "first look")
        if info["size"] == st["size"] and info["mtime"] == st["mtime"]:
            return
        save = info.get("SAVE", "")
        if save == st.get("save"):
            return self._guard(info, "changed without a save of hers (slot loaded?)")
        run = info.get("RUN", "")
        if "NEW_CLEAN" in run:
            return self._guard(info, "saved by a mapping run")
        if info["size"] >= SHRINK * st["size"]:
            return self._guard(info, "saved by a tracking run")
        # shrunk after a tracking run: only touch her files while she's docked/idle
        now = info.get("NOW", "")
        if "WORKING.IDLE" not in now:
            _log("map shrank; waiting until she's idle to put it back")
            return
        r = self.map_slots("load", "_guard")
        when = (re.search(r"\d\d:\d\d:\d\d", save) or [""])[0]
        if r.get("ok"):
            self.state["mtime"] = -1               # the restored file is re-guarded next check
            self.state["save"] = save
            self._save_state()
            _log(f"restored the guard map ({st['size']} bytes) over {info['size']} bytes")
            _notify(f"Lucy: her run saved a much smaller map at {when} ({info['size'] // 1024} KB vs "
                    f"{st['size'] // 1024} KB), so I've put her previous map back. The small one is "
                    f"kept as a _before_ slot on the map page if you want it.")
        else:
            _log(f"restore failed: {r.get('out')}")

    def _run(self):
        time.sleep(20)
        while True:
            try:
                self.check()
                if time.time() - self.state.get("backup_at", 0) > BACKUP_EVERY_S:
                    self.backup()
            except Exception as e:                  # keep guarding; report the problem
                _log(f"error: {e}")
            time.sleep(EVERY_S)
