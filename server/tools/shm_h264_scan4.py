import gzip, struct, re
for name, stride in (("h264", 0x400000), ("cg", 0x100000)):
    d = gzip.open(rf"captures\shm\{name}.gz").read()
    for k in range(3):
        base = 0x1000 + k*stride
        win = d[base:base+0x400]
        i = win.find(b"\x01" + b"\x00"*7)
        while i >= 0:
            ts, ln = struct.unpack_from("<QQ", win, i+8)
            if ts > 10**12 and 0 < ln < stride: break
            i = win.find(b"\x01" + b"\x00"*7, i+1)
        if i < 0: print(name, k, "no meta"); continue
        msg = d[base+i+24: base+i+24+ln]
        nals = [(m.start(), msg[m.end()] & 0x1f) for m in re.finditer(rb"\x00\x00\x00\x01", msg)]
        print(f"{name} slot{k} meta@{i:#x} ts={ts} len={ln} NALs={[(hex(a),t) for a,t in nals][:6]} msg[:24]={msg[:24].hex(' ')}")
