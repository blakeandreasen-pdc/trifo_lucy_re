"""Security mode: her own motion detection, switched on from the control page (2026-10-26).

What she does (found 26 Oct): SET_MONITOR_STATE "1"/"0" (rx key 15) sets system_config
monitor_mode. While it's on she stays docked, silent (no voice prompt), and her perception node
watches the depth camera's point cloud for movement ("PCD motion detection"). Each detection is
saved in /data/user/app/monitor/ as <unix time>.jpg (a 480x270 still) plus <unix time>.gif,
which is NOT a GIF: a few header bytes, then ~13 colour JPEG frames (480x270) followed by ~16
night-vision frames, glued together. No sound. One row per event in data.db monitor_record.
The old app fetched these from the cloud; she doesn't try to upload them any more.

This watcher (a thread in lucy_stream.py) checks every 20 s while the mode is on, copies new
events to security/ here (never committed to git: they're pictures of the house), turns each
into a real animated GIF for the page, and sends a text-only note (no pictures), at most one per 10 minutes."""
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

import lucy_live

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "security")
NOTIFY_GAP_S = 600
PROBE = """cd /data/user/app
sqlite3 data.db "select value from system_config where key_name='monitor_mode'" | sed 's/^/MODE /'
ls monitor | sed 's/^/FILE /'
"""
_state = {"on": None, "checked": 0, "last_note": 0}
_lock = threading.Lock()


def _rx(cmd, data, key):
    body = json.dumps({"cmd": cmd, "data": data, "key": key, "wait": 0}).encode()
    req = urllib.request.Request("http://127.0.0.1:8080/api/rxcmd", data=body, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).read()


def set_mode(on):
    _rx("SET_MONITOR_STATE", "1" if on else "0", "15")
    time.sleep(1.5)
    return check()


def _frames(blob):
    """Split her pseudo-GIF into JPEG frames (PIL images)."""
    from PIL import Image
    out, i = [], 0
    while True:
        s = blob.find(b"\xff\xd8\xff", i)
        if s < 0:
            return out
        e = blob.find(b"\xff\xd9", s)
        while e >= 0:
            try:
                im = Image.open(io.BytesIO(blob[s:e + 2]))
                im.load()
                out.append(im.convert("RGB"))
                break
            except Exception:
                e = blob.find(b"\xff\xd9", e + 2)
        if e < 0:
            return out
        i = e + 2


def _pull(name):
    cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [lucy_live.SSH_HOST, f"cat /data/user/app/monitor/{name}"]
    return subprocess.run(cmd, capture_output=True, timeout=60).stdout


def _save_event(t):
    """Copy event t from her and make security/<t>.gif (colour frames, then night vision) + <t>.jpg."""
    still = _pull(f"{t}.jpg")
    blob = _pull(f"{t}.gif")
    if still:
        open(os.path.join(DIR, f"{t}.jpg"), "wb").write(still)
    frames = _frames(blob) if blob else []
    if frames:
        # night-vision frames are smaller: pad them onto the colour frame size
        from PIL import Image
        W, H = frames[0].size
        fixed = []
        for f in frames:
            if f.size != (W, H):
                c = Image.new("RGB", (W, H))
                g = f.copy()
                g.thumbnail((W, H))
                c.paste(g, ((W - g.width) // 2, (H - g.height) // 2))
                f = c
            fixed.append(f)
        fixed[0].save(os.path.join(DIR, f"{t}.gif"), save_all=True, append_images=fixed[1:], duration=150, loop=0)
    return len(frames)


def _notify(text):
    print(f"[notify] {text}", flush=True)     # plug your own messenger in here


def _ntfy(topic, name, text):
    """ntfy (ntfy.sh or a self-hosted server): a push to anyone subscribed to the topic in the
    ntfy app. Text only. A bare topic means https://ntfy.sh/<topic>; pick a long, unguessable one,
    since anyone who knows it can read (and send to) it."""
    url = topic if topic.startswith("http") else "https://ntfy.sh/" + topic
    try:
        req = urllib.request.Request(url, data=text.encode(), headers={"Title": f"{name}: movement", "Tags": "rotating_light"})
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print(f"[security] ntfy failed: {e}", flush=True)


def check():
    """One SSH look: mode on/off, and copy any events we don't have yet. -> state dict."""
    with _lock:
        out = lucy_live.ssh_run(PROBE, timeout=30)
        if out is None:
            return status()
        names = []
        for line in out.decode(errors="replace").splitlines():
            if line.startswith("MODE "):
                _state["on"] = line[5:].strip() == "1"
            elif line.startswith("FILE "):
                names.append(line[5:].strip())
        _state["checked"] = time.time()
        os.makedirs(DIR, exist_ok=True)
        have = set(os.listdir(DIR))
        new = sorted({m.group(1) for n in names for m in [re.match(r"(\d+)\.jpg$", n)] if m} - {n[:-4] for n in have if n.endswith(".jpg")})
        for t in new:
            n = _save_event(t)
            print(f"[security] event {t}: {n} frames", flush=True)
        fresh = [t for t in new if time.time() - int(t) < 900]      # not old clips found after a restart
        settings = _load_settings()
        if fresh and time.time() - _state["last_note"] > NOTIFY_GAP_S:
            _state["last_note"] = time.time()
            when = time.strftime("%H:%M", time.localtime(int(fresh[0])))
            name = (settings.get("name") or "Lucy").capitalize()
            text = f"{name} saw movement at {when}" + (f" ({len(fresh)} clips)" if len(fresh) > 1 else "") + "."
            if settings.get("secnotify", True):
                _notify(text + " Clips are on her page under Security: http://YOUR_SERVER_IP:8090/view")
            if settings.get("ntfy"):
                _ntfy(settings["ntfy"], name, text)
        return status()


def _load_settings():
    try:
        return json.load(open(os.path.join(HERE, "settings.json"), encoding="utf-8"))
    except Exception:
        return {}


def status():
    try:
        ev = sorted((n[:-4] for n in os.listdir(DIR) if n.endswith(".jpg")), reverse=True)
    except OSError:
        ev = []
    return {"on": _state["on"], "checked": _state["checked"],
            "events": [{"t": int(t), "gif": os.path.exists(os.path.join(DIR, t + ".gif"))} for t in ev[:60]]}


def watch():
    """Thread: every 20 s while security mode is on (every 5 minutes otherwise, to notice the app
    or a restart changing it)."""
    time.sleep(15)
    while True:
        try:
            if _state["on"] or time.time() - _state["checked"] > 300:
                check()
        except Exception as e:
            print(f"[security] error: {e}", flush=True)
        time.sleep(20)
