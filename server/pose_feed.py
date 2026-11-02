"""Her live map pose, ~5 per second: one long-lived `ssh ... zq mapper-global_pose SUB` (a ZeroMQ
PUB socket of her mapper; found 2026-10-22). Each frame is Pose2D {1 x double, 2 y double,
3 theta double, 5/7 timestamps}, in the same map frame as /api/map (the slower strace-based
pose in map_reader.py is the same message).
Other feeds on the same pattern (/data/local/tmp/<name>, SUB): txen_driver-bot_data (~100 Hz,
sensors), *-barrier_range_data and point_cloud_preprocessor-filtered_sensor_data (silent while
she's idle)."""
import collections
import math
import struct
import subprocess
import threading
import time

import lucy_live

ZQ = "/data/lucy_local/zq"
PAUSED = False            # video tests: stop both feeds on her while set
SOCK = "/data/local/tmp/mapper-global_pose"


def decode_pose(b):
    """-> {x, y, theta, ts_ms} (ts = field 5, her boot clock in ms: the pose's own time; while she's
    still the mapper keeps re-sending the last pose with its old ts)."""
    out, i = {}, 0
    names = {1: "x", 2: "y", 3: "theta"}
    while i < len(b):
        key = b[i]
        i += 1
        f, wt = key >> 3, key & 7
        if wt == 1:
            if f in names:
                out[names[f]] = struct.unpack_from("<d", b, i)[0]
            i += 8
        elif wt == 0:
            v = sh = 0
            while True:
                c = b[i]
                i += 1
                v |= (c & 0x7f) << sh
                sh += 7
                if c < 0x80:
                    break
            if f == 5:
                out["ts_ms"] = v
        else:
            break
    return out if all(k in out for k in names.values()) else None


class PoseFeed:
    def __init__(self):
        self.pose = None
        self.at = 0.0
        self.history = collections.deque(maxlen=150)    # (ts_ms, pose), ~30 s
        self.new_at = 0.0
        threading.Thread(target=self._run, daemon=True).start()

    def get(self):
        return {"pose": self.pose, "age": round(time.time() - self.at, 2) if self.at else None}

    def _run(self):
        while True:
            cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [
                lucy_live.SSH_HOST, f"renice -n 19 -p $PPID >/dev/null 2>&1; exec nice -n 19 {ZQ} {SOCK} SUB - 2000000000"]
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
                for line in p.stdout:
                    if PAUSED:
                        p.kill()
                        break
                    line = line.decode(errors="replace")
                    if not line.startswith("frame"):
                        continue
                    try:
                        pose = decode_pose(bytes.fromhex(line.rsplit(":", 1)[1].strip()))
                    except (ValueError, IndexError, struct.error):
                        continue
                    if pose and all(abs(pose[k]) < 1000 for k in ("x", "y", "theta")):
                        self.pose, self.at = pose, time.time()
                        if "ts_ms" in pose and (not self.history or pose["ts_ms"] > self.history[-1][0]):
                            self.history.append((pose["ts_ms"], pose))
                            self.new_at = time.time()

            except OSError:
                pass
            time.sleep(3)
            while PAUSED:
                time.sleep(0.5)

    def at_time(self, ts_ms):
        """Her pose at ts_ms (boot clock), interpolated between the two poses around it; None if
        we don't have a pose after it yet (or the gap is over 0.5 s)."""
        h = list(self.history)
        for (t0, p0), (t1, p1) in zip(h, h[1:]):
            if t0 <= ts_ms <= t1:
                if t1 - t0 > 500:
                    return None
                f = (ts_ms - t0) / (t1 - t0) if t1 > t0 else 0
                dth = math.atan2(math.sin(p1["theta"] - p0["theta"]), math.cos(p1["theta"] - p0["theta"]))
                return {"x": p0["x"] + f * (p1["x"] - p0["x"]), "y": p0["y"] + f * (p1["y"] - p0["y"]),
                        "theta": p0["theta"] + f * dth}
        if h and h[-1][0] <= ts_ms and time.time() - self.new_at > 0.6 and time.time() - self.at < 1:
            return h[-1][1]          # no new poses for a while: she's still, the last pose holds
        return None


class DepthFeed:
    """Obstacle points from her ToF camera, ~5 per second: onrobot/depthscan on Lucy turns each
    point cloud into 2 cm cells that stick up 1.5-11 cm above the floor (floor plane from
    depth_calib.json), in her own frame (forward, left; metres; her centre = 0,0)."""
    CAM_FWD = 0.152            # camera ~2.3 cm behind her front edge (bump test 2026-10-24)
    H_MIN, H_MAX = 0.02, 0.11      # depthscan adds 2.5 cm per metre of distance

    def __init__(self):
        import json
        import os
        cal = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "depth_calib.json")))
        self.args = f"{cal['a']:.5f} {cal['b']:.5f} {cal['c']:.5f} {self.CAM_FWD} {self.H_MIN} {self.H_MAX} 5"
        self.pts, self.at, self.ts = [], 0.0, 0
        self.frames = collections.deque(maxlen=50)       # (ts_us, pts), ~10 s: the aligner fits them all
        self.asked = time.time()                          # last get(): stop depthscan when unused
        threading.Thread(target=self._run, daemon=True).start()

    def get(self, poses=None, touch=True, last=None):
        """Live points, plus "placed": recent frames each with her pose at its capture time (for
        the page's memory of what the camera saw; frames without a matching pose yet are left out)."""
        if touch:
            self.asked = time.time()
        placed = []
        if poses is not None:
            for ts, pts in list(self.frames)[-last if last else 0:]:
                pose = poses.at_time(ts / 1000)
                if pose:
                    placed.append({"ts": ts, "pose": pose, "pts": pts})
        return {"pts": self.pts, "age": round(time.time() - self.at, 2) if self.at else None,
                "placed": placed}

    def _run(self):
        while True:
            cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [
                lucy_live.SSH_HOST, f"renice -n 19 -p $PPID >/dev/null 2>&1; exec nice -n 19 /data/lucy_local/depthscan {self.args}"]
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
                for line in p.stdout:
                    if time.time() - self.asked > 30 or PAUSED:   # nobody looking: stop it on her
                        p.kill()
                        break
                    parts = line.decode(errors="replace").split()
                    if len(parts) < 3 or parts[0] != "S":
                        continue
                    pts = []
                    for cell in parts[3:]:
                        f, _, l = cell.partition(",")
                        pts.append([int(f) / 100, int(l) / 100])
                    self.pts, self.at, self.ts = pts, time.time(), int(parts[1])
                    self.frames.append((self.ts, pts))
            except (OSError, ValueError):
                pass
            time.sleep(3)
            while time.time() - self.asked > 30 or PAUSED:
                time.sleep(0.5)
