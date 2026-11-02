"""Line her map up with what the depth camera actually sees (for the parking view).

Her map pose can be ~20 cm out locally (bump tests 2026-10-24: the same world-frame shift at two
walls 90 deg apart), which is fine for cleaning but not for a parking sensor. Every second this
takes the depth points of the last ~10 s (was 3 s until 2026-10-25: more walls in more directions pin her down better), each frame placed at her pose from its capture time
(DepthFeed.get(PoseFeed)), and finds the small shift/turn (up to +-30 cm, +-10 deg, about her
current position) that puts them best onto the walls of her map. Score = mean distance from each
point to the nearest map wall (capped at 10 cm), via a distance transform of the map.

Result: corr = {dx, dy, dth, cx, cy}: a point p in her pose frame belongs at R(dth)(p - c) + c + d
in the map. The page applies that to her pose before looking up map obstacles."""
import base64
import json
import math
import threading
import time
import urllib.request

import numpy as np
import pose_feed
from scipy import ndimage

OCC = 170                 # map cells this solid count as walls
CAP = 0.10                # m: score cap per point
SHIFT = 0.45              # m search range (0.30 was hit at times)
STEP = 0.02
ANGLES = np.radians(np.arange(-10, 10.5, 1.0))
# A straight wall can't say where along it she is, so prefer the correction closest to the last one
# (or to none): each 10 cm of change costs 2 mm of score, each degree 0.5 mm.
LAMBDA_D, LAMBDA_TH = 0.02, 0.03
MAPS_OFF = False          # video tests: no map pulls from her


class Aligner:
    def __init__(self, depth, poses):
        self.depth, self.poses = depth, poses
        self.map = None
        self.map_at = 0.0
        self.corr = None
        self.info = {}
        self.wake = threading.Event()
        self.asked = time.time()   # idle (no map pulls from her) when the page isn't asking
        self.fresh = False         # next fit ignores the previous correction (manual "re-align")
        threading.Thread(target=self._run, daemon=True).start()

    def realign(self):
        self.asked = time.time()
        """Forget the current correction and fit again straight away from scratch."""
        self.corr, self.fresh = None, True
        self.wake.set()
        return {"ok": True}

    def get(self):
        self.asked = time.time()
        return {"corr": self.corr, **self.info}

    def _load_map(self):
        m = json.load(urllib.request.urlopen("http://127.0.0.1:8080/api/map", timeout=30))
        if not m.get("ok"):
            return
        a = np.frombuffer(base64.b64decode(m["cells_b64"]), np.uint8).reshape(m["height"], m["width"])
        cs = m["cell_size"]
        dist = ndimage.distance_transform_edt(a < OCC) * cs
        self.map = {"dist": np.minimum(dist, CAP).astype(np.float32), "cs": cs,
                    "max_x": m["max_x"], "max_y": m["max_y"], "h": a.shape[0], "w": a.shape[1]}
        self.map_at = time.time()

    def _score(self, X, Y):
        """X, Y: arrays (..., N) of map points -> mean capped distance to walls along the last axis."""
        m = self.map
        r = np.clip(((m["max_x"] - X) / m["cs"]).astype(np.int32), 0, m["h"] - 1)
        c = np.clip(((m["max_y"] - Y) / m["cs"]).astype(np.int32), 0, m["w"] - 1)
        return m["dist"][r, c].mean(axis=-1)

    def _points(self):
        d = self.depth.get(self.poses, touch=False)
        pts = []
        for fr in d.get("placed", []):
            p = fr["pose"]
            c, s = math.cos(p["theta"]), math.sin(p["theta"])
            for f, l in fr["pts"]:
                pts.append((p["x"] + f * c - l * s, p["y"] + f * s + l * c))
        if not pts:
            return np.zeros((0, 2))
        P = np.unique(np.round(np.array(pts), 2), axis=0)
        if len(P) > 1000:                     # keep the fit ~1 s on the Surface
            P = P[np.random.default_rng(0).choice(len(P), 1000, replace=False)]
        return P

    def _run(self):
        while True:
            self.wake.wait(1)
            self.wake.clear()
            if time.time() - self.asked > 30 or pose_feed.PAUSED:
                continue
            try:
                if not MAPS_OFF and (self.map is None or time.time() - self.map_at > 60):
                    self._load_map()
                if self.map is None or not self.poses.pose:
                    continue
                if time.time() - self.depth.at > 2:
                    self.info = {"note": "no live depth (camera off, e.g. docked)"}
                    continue                    # old frames would just re-fit stale points
                P = self._points()
                if len(P) < 40:
                    self.info = {"n": int(len(P)), "note": "not enough depth points", "decision": "too few walls in view"}
                    continue
                cx, cy = self.poses.pose["x"], self.poses.pose["y"]
                rel = P - (cx, cy)
                shifts = np.arange(-SHIFT, SHIFT + 1e-9, STEP)
                DX, DY = np.meshgrid(shifts, shifts, indexing="ij")
                DX, DY = DX.ravel()[:, None], DY.ravel()[:, None]
                score0 = float(self._score(P[:, 0][None], P[:, 1][None])[0])
                prev = self.corr if not self.fresh and self.corr and math.hypot(self.corr["cx"] - cx, self.corr["cy"] - cy) < 1 else None
                pdx, pdy, pth = (prev["dx"], prev["dy"], prev["dth"]) if prev else (0.0, 0.0, 0.0)
                best = (score0 + LAMBDA_D * math.hypot(pdx, pdy) + LAMBDA_TH * abs(pth), 0.0, 0.0, 0.0, score0)
                for th in ANGLES:
                    c, s = math.cos(th), math.sin(th)
                    rx = cx + rel[:, 0] * c - rel[:, 1] * s
                    ry = cy + rel[:, 0] * s + rel[:, 1] * c
                    raw = self._score(rx[None] + DX, ry[None] + DY)
                    cost = raw + LAMBDA_D * np.hypot(DX[:, 0] - pdx, DY[:, 0] - pdy) + LAMBDA_TH * abs(th - pth)
                    i = int(np.argmin(cost))
                    if cost[i] < best[0]:
                        best = (float(cost[i]), float(DX[i, 0]), float(DY[i, 0]), float(th), float(raw[i]))
                _, dx, dy, th, sc = best
                self.info = {"n": int(len(P)), "score0": round(score0, 4), "score": round(sc, 4),
                             "at": time.time()}
                # only trust a clear improvement; ease towards it so the view doesn't jump about
                at_edge = abs(dx) >= SHIFT - 1e-6 or abs(dy) >= SHIFT - 1e-6 or abs(th) >= ANGLES[-1] - 1e-6
                self.info["at_edge"] = bool(at_edge)
                self.info["decision"] = ("answer at the edge of the search: ignored" if at_edge else
                                         "lined up" if sc < 0.7 * score0 and sc < 0.04 else
                                         "no clear better fit: left as is")
                # an answer at the edge of the search is a guess (lost, or a doubled wall): skip it
                if sc < 0.7 * score0 and sc < 0.04 and not at_edge:
                    new = {"dx": dx, "dy": dy, "dth": th, "cx": cx, "cy": cy}
                    if not self.fresh and self.corr and math.hypot(self.corr["cx"] - cx, self.corr["cy"] - cy) < 1:
                        k = 0.5
                        new = {key: self.corr[key] + k * (new[key] - self.corr[key])
                               for key in ("dx", "dy", "dth")} | {"cx": cx, "cy": cy}
                    self.corr = {k: round(v, 4) for k, v in new.items()}
                    self.fresh = False
            except Exception as e:          # keep the thread alive; report the problem
                self.info = {"error": str(e)[:200]}
