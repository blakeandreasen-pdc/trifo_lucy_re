"""
Live H.264 video from Lucy's cameras, served over HTTP for VLC.

    python lucy_stream.py [--keepalive] [--port 8090] [--record file.h264]

Then open in VLC (Media > Open Network Stream):
    http://YOUR_SERVER_IP:8090/lucy.h264    main camera, 1920x1080 @ 20 fps
    http://YOUR_SERVER_IP:8090/depth.h264   "cg" camera, 224x172 @ 10 fps (likely the ToF depth sensor)

How it works (found 2026-10-14): the camera node writes hardware-encoded H.264 into
3-slot rings in /dev/shm (4 KiB header, slots from 0x1000). Each slot: u64 1 | u64 ts_us |
u64 len | protobuf whose bytes field holds Annex-B NAL units (SPS/PPS in-band with every
keyframe). Slot k's meta sits at 0x8c + 0x20*k within its slot. We read the rings through
one long-lived /system/bin/sftp-server per stream (random-access reads, no forks on Lucy),
order frames by timestamp and fan them out to HTTP clients.

The cameras only run while Lucy is active. --keepalive holds manual mode open
(MANCTRL S + K every 3 s, no driving) so they stay on while docked. Don't use it during a
cleaning run: entering manual mode would interrupt the run.
"""
import argparse
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import align
import drive_link
import fmp4
import lucy_live
import map_preview
import pose_feed

CHUNK = 32768
# prefix for commands we run on her: drop the SSH session ($PPID) and the command to lowest priority
NICE = "renice -n 19 -p $PPID >/dev/null 2>&1; exec nice -n 19 "
IDLE_STOP_S = 10          # stop reading a camera ring this long after its last viewer leaves             # sftp-server caps read size; fetch frames in pieces


class Sftp:
    """Minimal SFTP v3 client over `ssh ... /system/bin/sftp-server` (pure stdlib).
    One long-lived sftp-server does random-access reads in-process, so polling a ring
    costs no forks on Lucy (a dd per read capped us at ~30 reads/s)."""

    def __init__(self):
        # lowest priority on her (the SSH session encrypting the video too): her navigation
        # stalled during map optimisation while we were using ~half a core (2026-10-24)
        cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [lucy_live.SSH_HOST, NICE + "/system/bin/sftp-server"]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, bufsize=0)
        self.next_id = 1
        self._send(1, struct.pack(">I", 3))                  # INIT v3
        t, _ = self._recv()
        if t != 2:
            raise IOError("sftp: no VERSION reply")

    def _send(self, t, payload):
        self.p.stdin.write(struct.pack(">IB", len(payload) + 1, t) + payload)
        self.p.stdin.flush()

    def _read_exact(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.p.stdout.read(n - len(buf))
            if not chunk:
                raise EOFError("sftp closed")
            buf += chunk
        return bytes(buf)

    def _recv(self):
        n, t = struct.unpack(">IB", self._read_exact(5))
        return t, self._read_exact(n - 1)

    def open(self, path):
        rid = self.next_id; self.next_id += 1
        p = path.encode()
        self._send(3, struct.pack(">II", rid, len(p)) + p + struct.pack(">II", 1, 0))
        t, body = self._recv()
        if t != 102:
            raise IOError("sftp: open failed")
        (hl,) = struct.unpack_from(">I", body, 4)
        self.handle = body[8:8 + hl]

    def read_req(self, offset, length):
        """Queue a READ; returns its request id (replies arrive via recv_data)."""
        rid = self.next_id; self.next_id += 1
        h = self.handle
        self._send(5, struct.pack(">II", rid, len(h)) + h + struct.pack(">QI", offset, length))
        return rid

    def recv_data(self):
        t, body = self._recv()
        (rid,) = struct.unpack_from(">I", body)
        if t == 103:
            (n,) = struct.unpack_from(">I", body, 4)
            return rid, body[8:8 + n]
        return rid, b""

    def close(self):
        try:
            self.p.kill()
        except Exception:
            pass


class Stream:
    """One camera ring: reads it from Lucy and fans frames out to HTTP viewers."""

    def __init__(self, name, shm, slot_stride, width, height):
        self.name, self.shm = name, shm
        self.width, self.height = width, height
        self.slot_base = [0x1000 + k * slot_stride for k in range(3)]
        self.meta_off = [0x8c + 0x20 * k for k in range(3)]
        self.max_len = slot_stride - 0x1000
        self.lock = threading.Lock()
        self.clients = []
        self.idle_since = None
        self.frames = 0
        self.torn = 0                    # frames dropped: slot overwritten while we read it
        self.broken = False              # a frame was dropped: hold back until the next keyframe
        self.skipped = 0                 # frames held back that way
        self.last_ts = 0
        self.last_frame_at = 0
        self.record = None

    # ---- viewers -------------------------------------------------------
    def add(self):
        q = {"buf": [], "started": False, "cv": threading.Condition()}
        with self.lock:
            self.clients.append(q)
        return q

    def remove(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def emit(self, ts, nal):
        if ts <= self.last_ts:
            self.broken = True               # arrived too late to use: same as a dropped frame
            return
        self.last_ts = ts
        self.frames += 1
        self.last_frame_at = time.time()
        key = b"\x00\x00\x00\x01\x27" in nal[:64] or (nal[4] & 0x1f) in (5, 7)
        # After a dropped (torn) frame, every later frame up to the next keyframe refers to a
        # picture the viewer never got: decoding them is what smears/tears the picture. Hold
        # them back so the view freezes for a moment instead (2026-10-25).
        if self.broken and not LAB["hold"]:
            self.broken = False
        if self.broken:
            if not key:
                self.skipped += 1
                return
            self.broken = False
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            with q["cv"]:
                if not q["started"]:            # new viewers start at a keyframe
                    if not key:
                        continue
                    q["started"] = True
                if q.get("broken") and not key:  # this viewer missed a frame: wait for a keyframe
                    continue
                q["broken"] = len(q["buf"]) >= 200      # drop if a viewer stalls
                if not q["broken"]:
                    q["buf"].append((ts, nal, key))
                q["cv"].notify()
        if self.record:
            self.record.write(nal)

    # ---- reader --------------------------------------------------------
    def run(self):
        while True:
            # only read her camera while someone is watching (or recording): reading both rings
            # around the clock cost her ~half a CPU core and Wi-Fi time even with nobody looking
            while not self.clients and not self.record:
                time.sleep(0.2)
            sf = None
            try:
                sf = Sftp()
                sf.open(self.shm)
                self._poll(sf)
            except Exception as e:
                print(f"[{self.name}] reader error: {e}", flush=True)
            if sf:
                sf.close()
            time.sleep(3)

    def _idle(self):
        if self.clients or self.record:
            self.idle_since = None
            return False
        if self.idle_since is None:
            self.idle_since = time.time()
        return time.time() - self.idle_since > IDLE_STOP_S

    def _poll(self, sf):
        # Poll each slot's meta continuously; when a slot holds a new frame, fetch it in
        # chunks, then emit frames oldest-first through a small reorder buffer.
        pending = {}                     # request id -> ("h", slot) | ("f", ts, chunk index)
        seen = [0, 0, 0]
        parts = {}                       # ts -> chunk list being fetched
        slot_of = {}                     # ts -> the slot it's being read from
        ready = []
        for k in range(3):
            pending[sf.read_req(self.slot_base[k] + self.meta_off[k], 24)] = ("h", k)
        while True:
            if self._idle():
                return                   # nobody watching: close the reader (run() waits)
            rid, data = sf.recv_data()
            tag = pending.pop(rid, None)
            if tag is None:
                continue
            if tag[0] == "h":
                k = tag[1]
                if len(data) == 24:
                    one, ts, ln = struct.unpack("<QQQ", data)
                    if one == 1 and ts and ts != seen[k] and 0 < ln < self.max_len:
                        seen[k] = ts
                        start = self.slot_base[k] + self.meta_off[k] + 24
                        n = (ln + CHUNK - 1) // CHUNK
                        parts[ts] = [None] * n
                        slot_of[ts] = k
                        for i in range(n):
                            pending[sf.read_req(start + i * CHUNK, min(CHUNK, ln - i * CHUNK))] = ("f", ts, i)
                        # re-read the meta straight after the chunks: sftp-server serves requests
                        # in order, so this tells us whether the slot changed while they were read.
                        # (Asking only once the chunks had come back over Wi-Fi flagged ~13% of
                        # good frames as torn, since the camera reuses a slot every 150 ms.)
                        pending[sf.read_req(self.slot_base[k] + self.meta_off[k], 24)] = ("c", k, ts)
                time.sleep(0.003)            # ~100 polls/s per slot
                pending[sf.read_req(self.slot_base[k] + self.meta_off[k], 24)] = ("h", k)
            elif tag[0] == "c":
                # re-read of the slot's meta after fetching a frame: if the camera has started
                # writing a newer frame into that slot meanwhile, our copy may be torn - drop it
                _, k, ts = tag
                chunks = parts.pop(ts, None)
                slot_of.pop(ts, None)
                msg = b"".join(chunks) if chunks and all(x is not None for x in chunks) else None
                if msg and (not LAB["torncheck"] or len(data) == 24 and struct.unpack("<QQQ", data)[1] == ts):
                    s = msg.find(b"\x00\x00\x00\x01")
                    if s >= 0:
                        ready.append((ts, msg[s:]))
                        ready.sort()
                else:
                    self.torn += 1
                    self.broken = True
                while ready and ((len(ready) > 2 and not parts) or len(ready) > 8):
                    self.emit(*ready.pop(0))
            else:
                _, ts, i = tag
                if ts not in parts:
                    continue
                parts[ts][i] = data          # judged when its "c" meta re-read arrives
                while ready and ((len(ready) > 2 and not parts) or len(ready) > 8):
                    self.emit(*ready.pop(0))


STREAMS = {
    "main": Stream("main", "/dev/shm/TrifoSemaphore_lucy_camera-image_data_h264", 0x400000, 1920, 1080),
    "depth": Stream("depth", "/dev/shm/TrifoSemaphore_lucy_camera-cg_encode_data", 0x100000, 224, 172),
}


def keepalive():
    def rx(cmd, data):
        body = json.dumps({"cmd": cmd, "data": data, "wait": 0}).encode()
        req = urllib.request.Request("http://127.0.0.1:8080/api/rxcmd", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass
    rx("MANCTRL", "S")
    while True:
        time.sleep(3)
        rx("MANCTRL", "K")


def waker():
    """Her cameras sleep while she's docked or idle. STREAM_CONTROL "1" (key 10, what the app's live
    view sends) wakes them for ~15 s with no manual mode and no brushes (just the cooling fan set
    quiet for the mic), so while anyone is watching and she's idle or the picture has stopped,
    resend it every 2.5 s. Nobody watching: nothing is sent and she's asleep again ~15 s later
    (found 2026-10-26)."""
    fwd = json.dumps({"cmd": "STREAM_CONTROL", "data": "1", "key": "10", "wait": 0}).encode()
    idle, checked = False, 0
    while True:
        time.sleep(2.5)
        watched = [st for st in STREAMS.values() if st.clients]
        if not watched:
            continue
        if time.time() - checked > 5:
            checked = time.time()
            try:
                st = json.loads(urllib.request.urlopen("http://127.0.0.1:8080/api/status", timeout=4).read())
                idle = bool(re.search(r"dock|charg|full|sleep|idle|pause", st.get("status_name", ""), re.I))
            except Exception:
                pass
        stalled = all(time.time() - st.last_frame_at > 6 for st in watched)
        if idle or stalled:
            try:
                urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/api/rxcmd", data=fwd,
                                       headers={"Content-Type": "application/json"}), timeout=5).read()
            except Exception:
                pass


# Video test switches (the page's "Video tests" box, /api/lab): flip features off live to see
# which one hurts the camera feed, without restarting the server.
LAB = {"hold": False,      # after a dropped frame, hold back frames until the next keyframe
                           # (off: Chloe found it made the feed worse, 2026-10-25)
       "torncheck": True,  # drop frames whose slot was rewritten while we read them
       "pace": "real",     # "real": frames last as long as the real gap; "fixed": 20 fps
       "feeds": True,      # her pose + depthscan feeds (parking view) and the map aligner
       "maps": True}       # map pulls from her (/api/map, aligner reloads)
DRIVE = None
POSE = None
DEPTH = None
ALIGN = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _frames(self, st):
        """Yield (ts, annexb, key) for one viewer until it disconnects."""
        q = st.add()
        print(f"[{st.name}] viewer connected {self.client_address}", flush=True)
        try:
            while True:
                with q["cv"]:
                    while not q["buf"]:
                        q["cv"].wait(5)
                    items = list(q["buf"])
                    q["buf"].clear()
                yield from items
        finally:
            st.remove(q)
            print(f"[{st.name}] viewer left {self.client_address}", flush=True)

    def _stream_h264(self, st):
        self.send_response(200)
        self.send_header("Content-Type", "video/h264")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for _, nal, _ in self._frames(st):
            self.wfile.write(nal)

    def _stream_mp4(self, st):
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        # The camera writes SPS/PPS/SEI as a separate tiny frame just before each IDR, so
        # collect parameter sets as they pass and start the fragments at the first IDR.
        seq, t0, frame_ticks = 0, None, fmp4.TIMESCALE // 20
        dt, prev_ts = 0, None              # decode time (ticks); camera ts of the last frame (us)
        sps = pps = None
        for ts, annexb, _ in self._frames(st):
            nals = fmp4.split_nals(annexb)
            types = [n[0] & 0x1f for n in nals]
            for n, t in zip(nals, types):
                if t == 7:
                    sps = n
                elif t == 8:
                    pps = n
            vcl = [n for n, t in zip(nals, types) if 1 <= t <= 5 or t == 6]
            if not any(1 <= t <= 5 for t in types):
                continue                      # no picture in this frame (parameter sets only)
            idr = 5 in types
            if t0 is None:
                if not (idr and sps and pps):
                    continue
                self.wfile.write(fmp4.init_segment(sps, pps, st.width, st.height))
                t0 = ts
            # Back-to-back decode times (each frame starts where the last one ended): using the
            # camera's real, jittery timestamps with a fixed duration left tiny holes in the
            # browser's buffer, so playback stalled and jumped about once a second. Each frame
            # lasts as long as the real gap since the previous one (clamped), so when frames are
            # dropped (torn reads, Wi-Fi) playback slows to match instead of running dry at a
            # nominal 20 fps and stalling (2026-10-24).
            if LAB["pace"] == "fixed":
                frame_ticks = fmp4.TIMESCALE // 20
            elif prev_ts is not None:
                frame_ticks = int(min(max(ts - prev_ts, 30000), 200000) * fmp4.TIMESCALE / 1e6)
            prev_ts = ts
            seq += 1
            self.wfile.write(fmp4.fragment(seq, dt, frame_ticks, vcl, idr))
            dt += frame_ticks

    def do_GET(self):
        path = self.path.split("?")[0]
        name, _, ext = path.strip("/").partition(".")
        st = STREAMS.get("main" if name == "lucy" else name)
        try:
            if st and ext == "h264":
                self._stream_h264(st)
            elif st and ext == "mp4":
                self._stream_mp4(st)
            elif path in ("/", "/view"):
                body = open(VIEW_PAGE, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif path in ("/park_view.js", "/runs.js", "/runs"):
                # page scripts and the full run list (runs.html), read per request
                fn = "runs.html" if path == "/runs" else path[1:]
                body = open(os.path.join(os.path.dirname(VIEW_PAGE), fn), "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8" if fn.endswith(".html") else "text/javascript; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/status":
                self._status()
            elif path == "/api/native":
                self._json({"id": native_stream_id()})
            elif path == "/api/pose":
                # live pose (~5 Hz) for the parking view
                global POSE
                if POSE is None:
                    POSE = pose_feed.PoseFeed()
                self._json(POSE.get())
            elif path == "/api/depth":
                # obstacle points from her depth camera, her own frame (parking view)
                global DEPTH
                if DEPTH is None:
                    DEPTH = pose_feed.DepthFeed()
                if POSE is None:
                    POSE = pose_feed.PoseFeed()
                self._json(DEPTH.get(POSE, last=15))     # the page needs ~3 s; the aligner uses all
            elif path == "/api/align":
                # correction lining her map up with the depth camera (align.py)
                global ALIGN
                if ALIGN is None:
                    if POSE is None:
                        POSE = pose_feed.PoseFeed()
                    if DEPTH is None:
                        DEPTH = pose_feed.DepthFeed()
                    ALIGN = align.Aligner(DEPTH, POSE)
                self._json(ALIGN.realign() if "now=1" in self.path else ALIGN.get())
            elif path == "/api/lab":
                self._json(LAB)
            elif path == "/api/settings":
                self._json(load_settings())
            elif path == "/api/security":
                import security
                self._json(security.check() if "check=1" in self.path else security.status())
            elif re.fullmatch(r"/security/\d+\.(gif|jpg)", path):
                # her security-mode clips, copied here by security.py
                import security
                fn = os.path.join(security.DIR, path.rsplit("/", 1)[1])
                if not os.path.exists(fn):
                    self.send_error(404)
                    return
                body = open(fn, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "image/gif" if fn.endswith(".gif") else "image/jpeg")
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(body)
            elif path == "/api/runs":
                # run log (run_log.py): cached, refreshed from her logs at most every 5 minutes
                import run_log
                m = re.search(r"limit=(\d+)", self.path)
                self._json(run_log.get(force="refresh=1" in self.path, limit=int(m.group(1)) if m else None))
            elif path.startswith("/api/robot/"):
                # the old control page's API (capture_server :8080): status, schedule
                self._json(urllib.request.urlopen("http://127.0.0.1:8080/api/" + path[len("/api/robot/"):], timeout=10).read())
            elif path == "/api/map" and not LAB["maps"]:
                self._json({"ok": False, "error": "map pulls switched off (video tests)"})
            elif path == "/api/map":
                # live map + pose from her SHM, via capture_server (map_reader caches 5 s)
                self._json(urllib.request.urlopen("http://127.0.0.1:8080/api/map", timeout=30).read())
            elif path == "/api/maps":
                self._json(map_slots("tsv"))
            elif path == "/api/mappreview":
                # PNG of a saved slot's map, drawn from its pbstream (map_preview.py; cached by size)
                q = urllib.parse.parse_qs(self.path.partition("?")[2])
                slot, size = q.get("slot", [""])[0], int(q.get("size", ["-1"])[0] or -1)
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", slot):
                    self._json({"error": "bad slot"})
                else:
                    with preview_lock:
                        try:
                            png, info = map_preview.preview(slot, size)
                        except Exception as e:
                            png, info = None, {"error": str(e)[:200]}
                    if "info" in q or not png:
                        self._json(info)
                    else:
                        body = open(png, "rb").read()
                        self.send_response(200)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Cache-Control", "max-age=60")
                        self.end_headers()
                        self.wfile.write(body)
            elif path == "/api/mapinfo":
                self._json(map_info())
            else:
                self.send_response(404)
                self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def do_POST(self):
        """Control proxy for the viewer page:
        /api/rx      {"cmd","data","key"}  -> capture_server /api/rxcmd (manual driving etc.)
        /api/speaker {"value"}             -> control port 9999 as DP 2 (dock, blowerMode:N)"""
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            if self.path == "/api/rx":
                fwd = json.dumps({"cmd": body.get("cmd", ""), "data": body.get("data", ""),
                                  "key": str(body.get("key", "2")), "wait": 0}).encode()
                req = urllib.request.Request("http://127.0.0.1:8080/api/rxcmd", data=fwd,
                                             headers={"Content-Type": "application/json"})
                result = urllib.request.urlopen(req, timeout=5).read()
            elif self.path == "/api/maps":
                # {"mode": "save"|"load"|"blank", "name": slot}; the page confirms first
                result = json.dumps(map_slots(body.get("mode", ""), body.get("name", ""))).encode()
            elif self.path == "/api/mapedit":
                result = json.dumps(map_edit(body)).encode()
            elif self.path.startswith("/api/robot/"):
                # run commands (start/pause/locate...) and schedule edits -> capture_server :8080
                req = urllib.request.Request("http://127.0.0.1:8080/api/" + self.path[len("/api/robot/"):],
                                             data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
                try:
                    result = urllib.request.urlopen(req, timeout=10).read()
                except urllib.error.HTTPError as e:
                    result = e.read() or json.dumps({"ok": False, "error": str(e)}).encode()
            elif self.path == "/api/say":
                # {"text", "voice"}: neural TTS played on her own speaker (say.py); takes ~10-20 s
                import say
                result = json.dumps(say.say(body.get("text", ""), body.get("voice", ""))).encode()
            elif self.path == "/api/lab":
                for k, v in body.items():
                    if k in LAB and (type(v) is type(LAB[k])):
                        LAB[k] = v
                pose_feed.PAUSED = not LAB["feeds"]
                align.MAPS_OFF = not LAB["maps"]
                print(f"[lab] {LAB}", flush=True)
                result = json.dumps(LAB).encode()
            elif self.path == "/api/drive":
                # joystick: {"lin", "turn"} every ~150 ms while held, {"end": true} to finish
                global DRIVE
                if DRIVE is None:
                    DRIVE = drive_link.DriveLink()
                result = json.dumps(DRIVE.end() if body.get("end") else
                                    DRIVE.update(float(body.get("lin", 0)), float(body.get("turn", 0)))).encode()
            elif self.path == "/api/settings":
                result = json.dumps(save_settings(body)).encode()
            elif self.path == "/api/security":
                import security
                result = json.dumps(security.set_mode(bool(body.get("on")))).encode()
            elif self.path == "/api/maprun":
                result = json.dumps(map_run(body)).encode()
            elif self.path == "/api/speaker":
                with socket.create_connection(("127.0.0.1", 9999), timeout=5) as s:
                    s.sendall(f"2:{body.get('value', '')}".encode())
                    result = json.dumps({"reply": s.recv(4096).decode(errors="replace")}).encode()
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(result)
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def _json(self, obj):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _status(self):
        body = json.dumps({s.name: {"frames": s.frames, "torn": s.torn, "skipped": s.skipped, "viewers": len(s.clients),
                                    "last_ts": s.last_ts} for s in STREAMS.values()}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


MTX_LOG = os.path.join("captures", "mediamtx.log")


def native_stream_id():
    """Lucy's own RTMP stream id (a fresh UUID per cloud_node start), from the newest
    'is publishing to path app-name/<uuid>' line in the MediaMTX log."""
    try:
        with open(MTX_LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(MTX_LOG) - 400000))
            text = f.read().decode(errors="replace")
    except OSError:
        return None
    ids = re.findall(r"is publishing to path 'app-name/([0-9a-f-]{36})'", text)
    return ids[-1] if ids else None


MAP_SLOTS_SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "map_slots.sh")
map_lock = threading.Lock()
preview_lock = threading.Lock()        # one preview at a time (each pulls ~1 MB from her)


def map_slots(mode, name=""):
    """Run tools/map_slots.sh on Lucy. tsv -> {"slots": [...], "current": str};
    save/load/blank -> {"ok", "out"}. load/blank restart cloud_node (~10 s)."""
    if mode not in ("tsv", "save", "load", "blank", "delete"):
        return {"ok": False, "out": "bad mode"}
    if mode in ("save", "load", "delete") and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name or ""):
        return {"ok": False, "out": "slot names: letters, digits, - and _ only"}
    with open(MAP_SLOTS_SH, encoding="utf-8") as f:
        script = f"MODE={mode}\nNAME={name}\n" + f.read().replace("\r\n", "\n") + "\n"
    with map_lock:
        out = lucy_live.ssh_run(script, timeout=60)
    if out is None:
        return {"ok": False, "out": "couldn't reach Lucy over SSH"}
    text = out.decode(errors="replace")
    if mode != "tsv":
        done = {"save": "saved slot", "load": "loaded slot", "blank": "blanked", "delete": "deleted slot"}[mode]
        return {"ok": done in text, "out": text.strip()}
    slots, current = [], ""
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        if parts[0] == "current":
            current = parts[2].strip()
        else:
            slots.append({"name": parts[0], "saved": parts[1], "info": parts[2].strip(),
                          "size": int(parts[3]) if len(parts) > 3 and parts[3].strip().isdigit() else 0})
    try:   # her reported state (MQTT, can lag) - shown on the page's confirm prompts
        state = json.loads(urllib.request.urlopen("http://127.0.0.1:8080/api/status", timeout=5).read())
        state = state.get("status_name") or state.get("status") or "unknown"
    except Exception:
        state = "unknown"
    return {"ok": True, "slots": slots, "current": current, "state": state}


def _points(b64):
    """Her point lists: base64 (MIME, CRLF-wrapped) of 104-byte records = 13 doubles, x,y first."""
    import base64
    raw = base64.b64decode(re.sub(r"\s", "", b64 or ""))
    return [list(struct.unpack_from("<2d", raw, i)) for i in range(0, len(raw) - 103, 104)]


def map_info():
    """Rooms (room_segmentation_info) and zones/walls (map_path) of the map in use, in map metres.
    map_path: path_type 0 = no-go zone (the one we've tested), state 1 = active."""
    script = ("cd /data/user/app\n"
              "sqlite3 -separator '\t' -newline '\n@@\n' data.db "
              "\"select 'room',map_id,room_id,room_type,ifnull(room_name,''),replace(contour,char(10),''),replace(seed,char(10),''),ifnull(selected,0) from room_segmentation_info\" "
              "\"select 'path',map_id,path_type,path_id,ifnull(path_name,''),replace(path_line,char(10),''),state from map_path\"\n")
    with map_lock:
        out = lucy_live.ssh_run(script, timeout=30)
    if out is None:
        return {"ok": False, "error": "couldn't reach Lucy over SSH"}
    rooms, paths = [], []
    for rec in out.decode(errors="replace").split("\n@@\n"):
        f = rec.strip("\r\n").split("\t")
        if f[0] == "room" and len(f) >= 7:
            seed = _points(f[6])
            rooms.append({"map": int(f[1]), "id": int(f[2]), "type": int(f[3] or 0), "name": f[4],
                          "contour": _points(f[5]), "seed": seed[0] if seed else None,
                          "selected": int(f[7] or 0) if len(f) > 7 else 0})
        elif f[0] == "path" and len(f) >= 7:
            paths.append({"map": int(f[1]), "type": int(f[2]), "id": int(f[3] or 0), "name": f[4],
                          "points": _points(f[5]), "state": int(f[6] or 0)})
    return {"ok": True, "rooms": rooms, "paths": paths}


def _encode_points(pts):
    """Inverse of _points: 104-byte records (x, y, then 11 zero doubles), base64 in 76-char
    lines with CRLF and no trailing newline - the same layout her own rows use."""
    import base64
    raw = b"".join(struct.pack("<13d", float(x), float(y), *([0.0] * 11)) for x, y in pts)
    return base64.encodebytes(raw).decode().rstrip("\n").replace("\n", "\r\n")


def _clean_name(s):
    return "".join(ch for ch in s if ch >= " ")


def _sql_text(s):
    s = re.sub(r"[\x00-\x1f']", "", str(s or ""))[:32]
    return "'" + s + "'"


def _map_mgr(msg):
    """Send a MapManageDataItemMsg to her as LUCY_MAP_MGR (rx key 18, base64), like the app."""
    import base64
    fwd = json.dumps({"cmd": "LUCY_MAP_MGR", "data": base64.b64encode(msg).decode(),
                      "key": "18", "wait": 0}).encode()
    req = urllib.request.Request("http://127.0.0.1:8080/api/rxcmd", data=fwd,
                                 headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=5).read().decode(errors="replace")


def map_edit(body):
    """Zones and room names, without restarting cloud_node (a restart makes her relocalise at the
    next run, which often fails - she then drops the zones and cleans everything).
    body: {"map": 1,
           "zones": [{"type": 0|1, "name": str, "points": [[x, y], ...]}],   # replaces types 0+1
           "rooms": [{"id": n, "name": str, "selected": 0|1}]}
    Zones go to her live, as the app sent them: LUCY_MAP_MGR POST, type PATH, MapPathInfoMsg
    {map_id, path_type, paths: Path2DMsg{path_id, path_name, pose[] (Affine2D theta/x/y), state 1}}
    per type (q2.t.m1); she replaces that type's rows in map_path herself.
    type 0 = keep-out (NO_GO_ZONE), 1 = clean zone (DESIGNATED_AREA).
    Room names only go into data.db (for this page); her own room handling doesn't need them.
    Saves a backup slot first."""
    import lucy_proto as P
    map_id = int(body.get("map", 1))
    msgs = []
    if "zones" in body:
        by_type = {0: [], 1: []}
        for i, z in enumerate(body["zones"]):
            ztype = int(z.get("type", 0))
            pts = [(float(x), float(y)) for x, y in z.get("points", [])]
            if ztype not in (0, 1) or not 3 <= len(pts) <= 32:
                return {"ok": False, "out": f"bad zone {i}"}
            by_type[ztype].append((_clean_name(str(z.get("name", "")))[:32], pts))
        for ztype, zs in by_type.items():
            info = P.pb_varint(1, map_id) + P.pb_varint(2, ztype)
            for pid, (name, pts) in enumerate(zs):
                path = P.pb_varint(1, pid) + P.pb_bytes(2, name or str(pid))
                for x, y in pts:
                    path += P.pb_bytes(3, P.pb_double(1, 0.0) + P.pb_double(2, x) + P.pb_double(3, y))
                path += P.pb_varint(4, 1)
                info += P.pb_bytes(3, path)
            msgs.append(P.pb_varint(1, P.POST) + P.pb_varint(3, P.TYPE_PATH) + P.pb_bytes(6, info))
    sql = [f"UPDATE room_segmentation_info SET room_name={_sql_text(r.get('name', ''))},"
           f" selected={1 if r.get('selected') else 0}"
           f" WHERE map_id={map_id} AND room_id={int(r['id'])};" for r in body.get("rooms", [])]
    slot = time.strftime("_before_edit_%Y%m%d_%H%M%S")
    with open(MAP_SLOTS_SH, encoding="utf-8") as f:
        save = f"MODE=save\nNAME={slot}\n" + f.read().replace("\r\n", "\n") + "\n"
    script = save + "cd /data/user/app\n"
    if sql:
        script += ("cat > /data/lucy_local/map_edit.sql <<'SQLEOF'\nBEGIN;\n" + "\n".join(sql)
                   + "\nCOMMIT;\nSQLEOF\nsqlite3 data.db < /data/lucy_local/map_edit.sql && echo 'rooms written'\n")
    with map_lock:
        out = lucy_live.ssh_run(script, timeout=60)
        if out is None:
            return {"ok": False, "out": "couldn't reach Lucy over SSH"}
        text = out.decode(errors="replace").strip()
        if sql and "rooms written" not in text:
            return {"ok": False, "out": text}
        for m in msgs:
            text += "\n" + _map_mgr(m)
        time.sleep(2)
        check = lucy_live.ssh_run("sqlite3 /data/user/app/data.db 'select path_type,path_id,path_name,state from map_path'\n", timeout=20)
    text += "\nher zone rows now: " + (check.decode(errors="replace").replace("\n", "  ") if check else "?")
    # the map guard restores whole slots (map + zones): keep its copy's zones current too
    g = map_slots("save", "_guard")
    if not g.get("ok"):
        text += "\n(couldn't refresh the map guard's copy: " + g.get("out", "")[:100] + ")"
    return {"ok": True, "out": text, "slot": slot}


def map_run(body):
    """Start a clean of just some clean zones (path_type 1) or rooms (3), the way the old app did:
    LUCY_MAP_MGR on rx key 18 = MapManageDataItemMsg{command RUN, reply_result 200,
    type PATH_COMMAND, path_command{map_id, path_type, path_ids}} (app: q2.t.l0 / k0)."""
    import lucy_proto as P
    ptype = int(body.get("type", P.DESIGNATED_AREA))
    ids = body.get("ids", [])
    if ids == "all" or body.get("check"):
        # from the schedule: "all" = every active clean zone (or room); listed ids are checked
        # against the map in use so a deleted zone or a swapped map doesn't start a stray run
        info = map_info()
        if not info.get("ok"):
            return {"ok": False, "out": info.get("error")}
        m = int(body.get("map", 1))
        have = ([z["id"] for z in info["paths"] if z["map"] == m and z["type"] == 1 and z["state"]] if ptype == P.DESIGNATED_AREA
                else [r["id"] for r in info["rooms"] if r["map"] == m])
        ids = have if ids == "all" else [i for i in map(int, ids) if i in have]
    ids = [int(i) for i in ids]
    if ptype not in (P.DESIGNATED_AREA, P.ROOM_SEGMENTATION) or not ids:
        return {"ok": False, "out": "need type 1 (zones) or 3 (rooms) and some ids"}
    msg = (P.pb_varint(1, P.RUN) + P.pb_varint(2, 200) + P.pb_varint(3, P.TYPE_PATH_COMMAND)
           + P.pb_bytes(7, P.path_command(int(body.get("map", 1)), ptype, ids)))
    return {"ok": True, "out": _map_mgr(msg)}


# Page settings that should follow the robot, not the phone (her name in the header). Kept next to
# this file, so a backup of this folder carries it (2026-10-26).
SETTINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
SETTING_KEYS = {"name": lambda v: re.sub(r"[\x00-\x1f<>]", "", str(v)).strip()[:24],
                "secnotify": bool,       # security mode: Telegram note when she sees movement
                "ntfy": lambda v: re.sub(r"[^A-Za-z0-9_\-:/.]", "", str(v))[:200]}   # ntfy topic or URL ("" = off)


def load_settings():
    try:
        return json.load(open(SETTINGS, encoding="utf-8"))
    except Exception:
        return {}


def save_settings(body):
    s = load_settings()
    for k, clean in SETTING_KEYS.items():
        if k in body:
            s[k] = clean(body[k])
    with open(SETTINGS + ".tmp", "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(SETTINGS + ".tmp", SETTINGS)
    return s


VIEW_PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "view.html")   # read per request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--keepalive", action="store_true")
    ap.add_argument("--record", help="also save the main camera stream to this .h264 file")
    a = ap.parse_args()
    if a.record:
        STREAMS["main"].record = open(a.record, "wb", buffering=0)
    # Feeds from an earlier run of this server (killed without cleanup) keep running on her and
    # compete with the video for Wi-Fi/CPU: stop them before starting new ones.
    lucy_live.ssh_run("pkill depthscan; pkill -f 'lucy_local/zq'", timeout=15)
    for st in STREAMS.values():
        threading.Thread(target=st.run, daemon=True).start()
    threading.Thread(target=waker, daemon=True).start()
    import security
    threading.Thread(target=security.watch, daemon=True).start()
    if a.keepalive:
        threading.Thread(target=keepalive, daemon=True).start()
    import map_guard
    map_guard.MapGuard(map_slots)        # puts her map back if a short run saves a tiny one over it
    print(f"viewer page: http://YOUR_SERVER_IP:{a.port}/view   (VLC: /lucy.h264, /depth.h264)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
