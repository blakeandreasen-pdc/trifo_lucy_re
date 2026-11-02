import gzip, struct, re
d = gzip.open(r"captures\shm\depth.gz").read()
print("size", len(d), "hdr", d[:32].hex(" "))
for k in range(3):
    base = 0x1000 + k*0x100000
    mo = 0x8c + 0x20*k
    one, ts, ln = struct.unpack_from("<QQQ", d, base+mo)
    msg = d[base+mo+24: base+mo+24+ln]
    print(k, one, ts, ln, msg[:40].hex(" "))
