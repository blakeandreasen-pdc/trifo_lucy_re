import gzip, re, struct, sys
for name in ("h264", "cg"):
    d = gzip.open(rf"captures\shm\{name}.gz").read()
    print("==", name, len(d), "header:", d[:64].hex(" "))
    starts = [m.start() for m in re.finditer(rb"\x00\x00\x00\x01", d)]
    print("start codes:", len(starts))
    for s in starts[:25]:
        nal = d[s+4] & 0x1f
        print(f"  @{s:#x} nal={nal}", d[max(0,s-32):s].hex(" ")[-95:] if nal in (7,5,1) and s<0x500000 else "")
    # non-zero regions
    regions=[]; i=0; step=4096
    while i < len(d):
        if d[i:i+step].strip(b"\x00"):
            j=i
            while j < len(d) and d[j:j+step].strip(b"\x00"): j+=step
            regions.append((i,j)); i=j
        else: i+=step
    print("nonzero regions:", [(hex(a),hex(b)) for a,b in regions][:12])
