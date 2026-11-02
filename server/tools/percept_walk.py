import gzip, struct, sys, re
sys.path.insert(0, r"<server folder>")
from lucy_live import _fields
d = gzip.open(r"captures\shm\percept.gz").read()
print("size", len(d), "hdr", d[:16].hex(" "))
for m in re.finditer(rb"\x01\x00\x00\x00\x00\x00\x00\x00", d):
    i = m.start()
    if i + 24 > len(d): break
    ts, ln = struct.unpack_from("<QQ", d, i + 8)
    if ts > 10**12 and 0 < ln < len(d):
        msg = d[i+24:i+24+ln]
        print("meta@", hex(i), "ts", ts, "len", ln)
        def walk(b, dep=0):
            for fn, v in _fields(b):
                if isinstance(v, tuple):
                    p, n = v
                    sub = b[p:p+n]
                    txt = sub.decode("latin1") if n < 60 and all(32 <= c < 127 for c in sub) else None
                    print("  "*dep + f"f{fn}: bytes {n}" + (f" '{txt}'" if txt else ""))
                    if not txt and n < 4000 and dep < 5:
                        try: walk(sub, dep+1)
                        except Exception: pass
                elif isinstance(v, bytes):
                    print("  "*dep + f"f{fn}: {struct.unpack('<f' if len(v)==4 else '<d', v)[0]:.3f}")
                else:
                    print("  "*dep + f"f{fn}: {v}")
        try: walk(msg)
        except Exception as e: print("walk err", e)
        break
