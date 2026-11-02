"""Measure what lucy_stream emits for ~15 s: frame gaps, keyframes, sizes. Keeps manual mode
on so the camera runs. Run while the LucyStream service is also up (separate sftp session)."""
import json
import sys
import threading
import time
import urllib.request

sys.path.insert(0, r"<server folder>")
import lucy_stream  # noqa: E402

log = []
st = lucy_stream.STREAMS["main"]
orig = st.emit


def emit(ts, nal):
    t = [n for n in (nal[i + 4] & 0x1f for i in range(len(nal) - 4) if nal[i:i + 4] == b"\x00\x00\x00\x01")]
    log.append((time.time(), ts, len(nal), t))
    orig(ts, nal)


st.emit = emit


def rx(cmd, data):
    body = json.dumps({"cmd": cmd, "data": data, "wait": 0}).encode()
    urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/api/rxcmd", data=body,
                                                  headers={"Content-Type": "application/json"}), timeout=5).read()


rx("MANCTRL", "S")
threading.Thread(target=st.run, daemon=True).start()
end = time.time() + 18
while time.time() < end:
    time.sleep(3)
    rx("MANCTRL", "K")

log = log[10:]                                   # skip start-up
gaps = [(b[1] - a[1]) / 1000 for a, b in zip(log, log[1:])]
idr = [(i, x) for i, x in enumerate(log) if 5 in x[3]]
print(f"frames {len(log)}, camera span {(log[-1][1] - log[0][1]) / 1e6:.1f}s, "
      f"fps {len(log) / ((log[-1][1] - log[0][1]) / 1e6):.1f}")
print("gaps >70ms:", [round(g) for g in gaps if g > 70])
print("IDR count", len(idr), "sizes KB", [round(x[2] / 1024) for _, x in idr][:8])
print("P sizes KB (sample)", [round(x[2] / 1024) for x in log[:12] if 5 not in x[3]])
arr = [round((b[0] - a[0]) * 1000) for a, b in zip(log, log[1:])]
print("emit wall-clock gaps >120ms:", [g for g in arr if g > 120])
