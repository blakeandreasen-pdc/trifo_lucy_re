"""Log any TCP connections (and first bytes) on the given ports. For spotting Lucy trying
to push video.   python port_listen.py 1935 554 8554 [seconds]"""
import select
import socket
import sys
import time

ports = [int(p) for p in sys.argv[1:] if p.isdigit() and int(p) < 65536 and len(p) <= 5]
secs = 120
socks = []
for p in ports:
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", p))
        s.listen(5)
        socks.append(s)
        print("listening", p, flush=True)
    except OSError as e:
        print("cannot bind", p, e, flush=True)
end = time.time() + secs
while time.time() < end:
    r, _, _ = select.select(socks, [], [], 1)
    for s in r:
        c, addr = s.accept()
        c.settimeout(3)
        try:
            data = c.recv(256)
        except OSError:
            data = b""
        print(time.strftime("%H:%M:%S"), "CONNECT on", s.getsockname()[1], "from", addr, data[:64], flush=True)
        c.close()
print("done", flush=True)
