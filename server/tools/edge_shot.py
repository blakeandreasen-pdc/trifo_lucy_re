"""Load a page in headless Edge, wait, then print a JS expression's value and save a
screenshot - via the DevTools protocol with a tiny stdlib WebSocket client.

    python edge_shot.py <url> <out.png> [wait_s] [js_expression]
"""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9333


class WS:
    def __init__(self, url):
        host, path = url[len("ws://"):].split("/", 1)
        h, p = host.split(":")
        self.s = socket.create_connection((h, int(p)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /{path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                        "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(4096)
        self.rest = buf.split(b"\r\n\r\n", 1)[1]
        self.next_id = 0

    def _recv_exact(self, n):
        while len(self.rest) < n:
            self.rest += self.s.recv(65536)
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def send(self, obj):
        data = json.dumps(obj).encode()
        mask = os.urandom(4)
        hdr = bytes([0x81])
        n = len(data)
        hdr += bytes([0x80 | n]) if n < 126 else (bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                                                  else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        msg = b""
        while True:
            b0, b1 = self._recv_exact(2)
            n = b1 & 0x7F
            if n == 126:
                (n,) = struct.unpack(">H", self._recv_exact(2))
            elif n == 127:
                (n,) = struct.unpack(">Q", self._recv_exact(8))
            msg += self._recv_exact(n)
            if b0 & 0x80:
                return json.loads(msg)

    def call(self, method, **params):
        self.next_id += 1
        self.send({"id": self.next_id, "method": method, "params": params})
        while True:
            r = self.recv()
            if r.get("id") == self.next_id:
                return r.get("result", r)


def main():
    url, out = sys.argv[1], sys.argv[2]
    wait = float(sys.argv[3]) if len(sys.argv) > 3 else 8
    expr = sys.argv[4] if len(sys.argv) > 4 else None
    prof = os.path.join(os.path.dirname(os.path.abspath(out)), "edge_cdp_profile")
    p = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}",
                          "--autoplay-policy=no-user-gesture-required", "--window-size=1300,700",
                          f"--user-data-dir={prof}", "about:blank"])
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.3)
        ws = WS(page["webSocketDebuggerUrl"])
        ws.call("Page.enable")
        ws.call("Page.navigate", url=url)
        time.sleep(wait)
        if expr:
            r = ws.call("Runtime.evaluate", expression=expr, returnByValue=True)
            print("JS:", r.get("result", {}).get("value"))
        shot = ws.call("Page.captureScreenshot", format="png")
        open(out, "wb").write(base64.b64decode(shot["data"]))
        print("saved", out)
    finally:
        p.kill()


if __name__ == "__main__":
    main()
