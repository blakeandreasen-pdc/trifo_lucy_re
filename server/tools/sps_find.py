import tarfile, struct, re
t = tarfile.open(r"captures\shm\sp.tgz")
found = {}
for m in t.getmembers():
    b = t.extractfile(m).read()
    i = b.find(b"\x01" + b"\x00"*7)
    while 0 <= i <= len(b) - 24:
        ts, ln = struct.unpack_from("<QQ", b, i + 8)
        if ts > 10**12 and 0 < ln < 4000:
            msg = b[i+24:i+24+ln]
            nals = [msg[x.end()] & 0x1f for x in re.finditer(rb"\x00\x00\x00\x01", msg)]
            if 7 in nals or 8 in nals:
                found[(m.name[0], ts)] = msg
            break
        i = b.find(b"\x01" + b"\x00"*7, i + 1)
for (cam, ts), msg in sorted(found.items()):
    s = msg.find(b"\x00\x00\x00\x01")
    print(cam, ts, len(msg), "NAL data from", s, msg[s:s+80].hex(" "))
    open(rf"captures\shm\sps_{cam}.bin", "wb").write(msg[s:])
print("found", len(found))
