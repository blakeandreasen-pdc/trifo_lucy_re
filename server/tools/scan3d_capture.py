"""3D scanner capture: keep Lucy's cameras awake (no motors) and stream onrobot/depthdump to disk.
Also logs her status and listens on the IMU socket.
  python tools/scan3d_capture.py <name> <seconds> [rgb_every_s]
Writes captures/scan3d/<name>/stream.bin, status.log, imu.txt; prints a progress line every 5 s."""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lucy_live import SSH_HOST, SSH_KEY, SSH_OPTS  # noqa: E402

API = "http://127.0.0.1:8080"
WAKE = json.dumps({"cmd": "STREAM_CONTROL", "data": "1", "key": "10", "wait": 0}).encode()


def ssh(cmd, **kw):
    return subprocess.Popen(["ssh", "-i", SSH_KEY] + SSH_OPTS + [SSH_HOST, cmd], **kw)


def main():
    name, secs = sys.argv[1], float(sys.argv[2])
    rgb_every = sys.argv[3] if len(sys.argv) > 3 else "3"
    out = Path(__file__).resolve().parent.parent / "captures" / "scan3d" / name
    out.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()

    def waker():
        with open(out / "status.log", "a") as log:
            while not stop.is_set():
                try:
                    urllib.request.urlopen(urllib.request.Request(API + "/api/rxcmd", data=WAKE, headers={"Content-Type": "application/json"}), timeout=4).read()
                    st = json.loads(urllib.request.urlopen(API + "/api/status", timeout=4).read())
                    log.write(f"{time.strftime('%H:%M:%S')} {st.get('status_name')} {st.get('status')} {st.get('position')}\n")
                    log.flush()
                except Exception as e:
                    log.write(f"{time.strftime('%H:%M:%S')} error {e}\n")
                stop.wait(2.5)

    threading.Thread(target=waker, daemon=True).start()
    time.sleep(4)
    imu = ssh(f"/data/lucy_local/zq /data/local/tmp/txen_driver-imu_data SUB 01 {int(secs * 1000)}",
              stdout=open(out / "imu.txt", "w"), stderr=subprocess.STDOUT)
    p = ssh(f"/data/lucy_local/depthdump {secs} {rgb_every} 25", stdout=open(out / "stream.bin", "wb"))
    t0 = time.time()
    while p.poll() is None:
        time.sleep(5)
        print(f"{time.strftime('%H:%M:%S')} {time.time() - t0:5.0f}s {os.path.getsize(out / 'stream.bin') / 1e6:7.1f} MB", flush=True)
    stop.set()
    imu.terminate()
    print("done", p.returncode)


if __name__ == "__main__":
    main()
