"""Intercom: play an audio file (or silence) through Lucy's speaker, optionally recording her
native stream (video + mic) at the same time.

    python tools\\talk.py captures\\talk_test.m4a            # say something
    python tools\\talk.py --silent 40 --record captures\\mic_test.mp4   # mic test

Talk only plays while her native live stream runs, so this holds manual mode (MANCTRL S/K) and
sends RTMP_THROB (key 10) every 5 s, pushes the audio to MediaMTX (ffmpeg in WSL), waits until
MediaMTX reports it publishing, then START_TALK (key 14). STOP_TALK goes out ~3 s before the
audio ends (otherwise she hammers reconnects). Ends with MANCTRL E + dock unless --no-dock.
"""
import argparse
import json
import re
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8080/api/rxcmd"
MTX_LOG = Path(os.path.join("captures", "mediamtx.log"))
RTMP = "rtmp://YOUR_SERVER_IP:1935/app-name/"
RTSP = "rtsp://YOUR_SERVER_IP:8554/app-name/"
TALK_ID = "claudetalk"


def rx(cmd, data="", key="2"):
    body = json.dumps({"cmd": cmd, "data": data, "key": key, "wait": 0}).encode()
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        print("rx failed:", cmd, e, flush=True)


def speaker(value):
    with socket.create_connection(("127.0.0.1", 9999), timeout=5) as s:
        s.sendall(f"2:{value}".encode())
        return s.recv(4096).decode(errors="replace")


def wsl_path(p):
    p = Path(p).resolve()
    return "/mnt/" + p.drive[0].lower() + p.as_posix()[2:]


def log_size():
    return MTX_LOG.stat().st_size


def wait_publish(start, pattern, timeout):
    """Wait for a NEW 'is publishing to path ...' line in the MediaMTX log after byte offset start."""
    rx_ = re.compile(r"is publishing to path '(app-name/" + pattern + r")'")
    end = time.time() + timeout
    while time.time() < end:
        with MTX_LOG.open("rb") as f:
            f.seek(start)
            for m in rx_.finditer(f.read().decode(errors="replace")):
                return m.group(1).split("/", 1)[1]
        time.sleep(0.5)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="?", help="audio file to play (AAC/m4a/wav/mp3)")
    ap.add_argument("--silent", type=float, help="play N seconds of silence instead")
    ap.add_argument("--listen", type=float,
                    help="no talk: just record N s of her stream (the mic is only live when NOT talking)")
    ap.add_argument("--record",help="record her native stream to this .mp4 while talking")
    ap.add_argument("--volume", type=int, help="setVolume:N for this talk (restored to 10 after)")
    ap.add_argument("--stream-control", action="store_true", help="also send STREAM_CONTROL 1 (key 10)")
    ap.add_argument("--no-dock", action="store_true")
    a = ap.parse_args()

    if a.listen:
        dur = a.listen
    elif a.silent:
        src = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(a.silent)]
        dur = a.silent
    else:
        dur = float(subprocess.run(["wsl", "-e", "ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", wsl_path(a.audio)], capture_output=True, text=True).stdout)
        src = ["-i", wsl_path(a.audio)]

    stop = threading.Event()

    def keepalive():
        n = 0
        while not stop.is_set():
            rx("MANCTRL", "K")
            if n % 2 == 0:
                rx("RTMP_THROB", "", key="10")
            if a.stream_control:
                # each STREAM_CONTROL 1 gives a 15 s mic/green-light window; repeats while it's
                # open are ignored, so resend often to re-arm it as soon as it lapses
                rx("STREAM_CONTROL", "1", key="10")
            n += 1
            stop.wait(2.5)

    if a.volume is not None:
        print("volume:", speaker(f"setVolume:{a.volume}"), flush=True)
    off = log_size()
    rx("MANCTRL", "S")
    rx("MANCTRL", "ANGLE:0")                    # cancel any queued A2B (it fires on manual start)
    time.sleep(1)
    rx("RTMP_THROB", "", key="10")
    if a.stream_control:
        rx("STREAM_CONTROL", "1", key="10")
    threading.Thread(target=keepalive, daemon=True).start()
    native = wait_publish(off, r"[0-9a-f-]{36}", 40)
    print("native stream:", native, flush=True)

    rec = None
    if a.record and native:
        rec = subprocess.Popen(["wsl", "-e", "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                                "-rtsp_transport", "tcp", "-i", RTSP + native, "-c", "copy",
                                "-t", str(dur + 10), wsl_path(a.record)])

    if a.listen:
        if rec:
            rec.wait(timeout=dur + 60)
        else:
            time.sleep(dur)
        rec = None
        push = None
    else:
        push = talk(a, src, dur)
    if push:
        push.wait(timeout=30)
        time.sleep(5)
    if rec:
        rec.wait(timeout=60)                    # ffmpeg stops itself (-t) so the mp4 gets finalised
    stop.set()
    if a.volume is not None:
        speaker("setVolume:10")
    if not a.no_dock:
        rx("MANCTRL", "E")
        time.sleep(1.5)
        print("dock:", speaker("dock"), flush=True)


def talk(a, src, dur):
    off = log_size()
    push = subprocess.Popen(["wsl", "-e", "ffmpeg", "-hide_banner", "-loglevel", "error", "-re", *src,
                             "-c:a", "aac", "-ar", "44100", "-ac", "1", "-f", "flv", RTMP + TALK_ID])
    t0 = time.time()
    if not wait_publish(off, TALK_ID, 25):
        print("talk audio never came online", flush=True)
    else:
        rx("START_TALK", TALK_ID, key="14")
        print("START_TALK", flush=True)
        remaining = dur - (time.time() - t0) - 3
        time.sleep(max(remaining, 2))
        rx("STOP_TALK", TALK_ID, key="14")
        print("STOP_TALK", flush=True)
    return push


if __name__ == "__main__":
    main()
