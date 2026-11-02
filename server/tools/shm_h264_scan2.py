import gzip, re
for name, stride in (("h264", 0x400000), ("cg", 0x100000)):
    d = gzip.open(rf"captures\shm\{name}.gz").read()
    print("==", name)
    for k in range(3):
        base = 0x1000 + k*stride
        print(f" slot {k} @{base:#x}:", d[base:base+48].hex(" "))
        seg = d[base:base+stride]
        sc = [(m.start(), seg[m.start()+4] & 0x1f) for m in re.finditer(rb"\x00\x00\x00\x01|\x00\x00\x01", seg)][:8]
        print("   NAL starts:", [(hex(a), t) for a, t in sc])
