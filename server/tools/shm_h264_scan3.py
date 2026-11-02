import gzip, struct
for name, stride, off in (("h264", 0x400000, 0xd5), ("cg", 0x100000, 0xd5)):
    d = gzip.open(rf"captures\shm\{name}.gz").read()
    for k in (1, 2):
        base = 0x1000 + k*stride
        o = off if k == 1 else 0xf5
        hdr = d[base+o-0x60:base+o]
        print(name, k, hdr.hex(" "))
        for j in range(0, len(hdr)-23, 8):
            a, b, c = struct.unpack_from("<QQQ", hdr, j)
            if a == 1 and b > 10**12:
                print("   meta at -%#x: ts=%d len=%d" % (0x60-j, b, c))
