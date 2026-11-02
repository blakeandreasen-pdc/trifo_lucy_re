"""Live driving for the page's joystick: one long-lived `ssh ... zq <motion socket> DEALER -s` to
Lucy, i.e. one ZeroMQ connection into sensor_node held open the way guidance does (see
drive_proto.py; found 2026-10-22); each command is one "@id:payloadhex" line. Measured: ~20 ms
from here to her motor log. (A new connection per command took 1-2 s to be picked up and
commands got merged; the first message on a new connection is dropped, so we prime with a stop.)

The page sends {"lin": -1..1, "turn": -1..1} about every 150 ms while the stick is held.
  - straight: move {forward 3 / back 4, speed, distance 1000 = keep going}; holds her heading
  - turning:  rotate {left, right wheel speeds, target 1000 = no target}: arcs, or a spin on the spot
  - centre:   stop
Smoothing: the stick is eased towards its new position (SMOOTH per 50 ms tick, ~0.15 s time
constant), so speed changes and stops are gentler; she still has her own acceleration on top.
Speeds are her "nominal" wheel units: guidance uses 4-8, and she tops out at about 10
(~0.25-0.3 m/s; higher values are capped). Safety: no update for 0.6 s while moving -> stop.
Manual mode (MANCTRL S, K every 3 s) keeps guidance out of the way while we drive; it lapses on
its own ~14 s after the keepalives stop, and we stop sending them 20 s after the last update."""
import subprocess
import threading
import time
import json
import urllib.request

import drive_proto as D
import lucy_live

ZQ = "/data/lucy_local/zq"
MOTION = "/data/local/tmp/TrifoIPC_planning_actor-motion_command_REQ"
VMAX = 10.0          # her real top speed
SPIN = 6.0           # wheel speed for spinning on the spot (guidance uses 6-8)
STEER = 6.0          # extra wheel-speed difference at full stick sideways
DEAD = 0.08
STALE_S = 0.6        # no update for this long -> ease to a stop
HARD_STOP_S = 1.5    # ... and a plain stop after this long
SMOOTH = 0.3
DEBUG = False        # log each command sent (stream_stdout.log)
MANUAL_IDLE_S = 20


def _rx(cmd, data, key="2"):
    body = json.dumps({"cmd": cmd, "data": data, "key": key, "wait": 0}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8080/api/rxcmd", data=body,
            headers={"Content-Type": "application/json"}), timeout=5).read()
    except OSError:
        pass


def wheels(lin, turn):
    """Stick -> ("stop",) | ("move", direction, speed) | ("rotate", left, right)."""
    lin = max(-1.0, min(1.0, lin))
    turn = max(-1.0, min(1.0, turn))
    if abs(lin) < DEAD and abs(turn) < DEAD:
        return ("stop",)
    if abs(turn) < DEAD:
        return ("move", 3 if lin > 0 else 4, round(abs(lin) * VMAX * 2) / 2)
    if abs(lin) < DEAD:
        s = round(turn * SPIN * 2) / 2
        return ("rotate", s, -s)                 # turn > 0 = clockwise (right)
    base, d = lin * VMAX, turn * STEER
    left, right = base + d, base - d
    scale = max(abs(left), abs(right)) / VMAX
    if scale > 1:
        left, right = left / scale, right / scale
    return ("rotate", round(left * 2) / 2, round(right * 2) / 2)


class DriveLink:
    def __init__(self):
        self.lock = threading.Lock()
        self.proc = None
        self.want = ("stop",)
        self.target = (0.0, 0.0)
        self.cur = (0.0, 0.0)
        self.sent = None
        self.sent_at = 0.0
        self.last_update = 0.0
        self.manual_since = None
        self.next_keep = 0.0
        self.rid = int(time.time()) % 100000 * 10
        threading.Thread(target=self._loop, daemon=True).start()

    # ---- called by the HTTP handler
    def update(self, lin, turn):
        with self.lock:
            if DEBUG and (lin, turn) != self.target:
                print(f"[drive] {time.time():.3f} stick {lin} {turn}", flush=True)
            self.target = (lin, turn)
            self.last_update = time.time()
            if self.manual_since is None:
                self.manual_since = time.time()
                threading.Thread(target=self._enter_manual, daemon=True).start()
        return {"cmd": list(self.want), "ready": self._ready()}

    def end(self):
        with self.lock:
            self.want = ("stop",)
            self.target = self.cur = (0.0, 0.0)
            self.last_update = 0.0
        self._send(("stop",))
        if self.manual_since is not None:
            self.manual_since = None
            _rx("MANCTRL", "E")
        return {"ok": True}

    # ---- internals
    def _ready(self):
        return self.manual_since is not None and time.time() - self.manual_since > 1.5

    def _enter_manual(self):
        try:
            self._shell()          # warm the link up now: a new connection takes ~1-2 s to be heard
        except OSError:
            self.proc = None
        _rx("MANCTRL", "S")
        time.sleep(1)
        _rx("MANCTRL", "ANGLE:0")
        self.next_keep = time.time() + 3

    def _shell(self):
        if self.proc is None or self.proc.poll() is not None:
            cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [
                lucy_live.SSH_HOST, f"{ZQ} {MOTION} DEALER -s"]   # normal priority: driving must stay snappy
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
            self.rid += 1
            self.proc.stdin.write(f"@{self.rid}:{D.stop(self.rid % 256).hex()}\n".encode())
            self.proc.stdin.flush()
        return self.proc

    def _send(self, want):
        if want[0] == "stop":
            self.rid += 1
            p = D.stop(self.rid % 256)
        elif want[0] == "move":
            self.rid += 1
            p = D.move(want[1], want[2], 1000.0, self.rid % 256)
        else:
            self.rid += 1
            p = D.rotate(want[1], want[2], 1000.0, self.rid % 256)
        line = f"@{self.rid}:{p.hex()}\n"
        for _ in range(2):
            try:
                sh = self._shell()
                sh.stdin.write(line.encode())
                sh.stdin.flush()
                break
            except OSError:
                self.proc = None
        self.sent, self.sent_at = want, time.time()
        if DEBUG:
            print(f"[drive] {time.time():.3f} {want}", flush=True)

    def _loop(self):
        while True:
            time.sleep(0.05)
            now = time.time()
            with self.lock:
                last = self.last_update
                if now - last > STALE_S:
                    self.target = (0.0, 0.0)              # page went quiet: ease to a stop
                if now - last > HARD_STOP_S:
                    self.cur = (0.0, 0.0)
                t, c = self.target, self.cur
                c = tuple(ci + (ti - ci) * SMOOTH for ci, ti in zip(c, t))
                if all(abs(ti) < DEAD for ti in t) and all(abs(ci) < DEAD for ci in c):
                    c = (0.0, 0.0)
                self.cur = c
                want = self.want = wheels(*c)
            if self.manual_since is None:
                continue
            if now - last > MANUAL_IDLE_S:
                self.manual_since = None                  # let manual mode lapse by itself
                continue
            if now >= self.next_keep and self._ready():
                self.next_keep = now + 3
                threading.Thread(target=_rx, args=("MANCTRL", "K"), daemon=True).start()
            if not self._ready():
                continue
            if want != self.sent or (want[0] != "stop" and now - self.sent_at > 2):
                self._send(want)
