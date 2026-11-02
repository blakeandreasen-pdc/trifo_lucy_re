import gzip, struct, sys
sys.path.insert(0, r"<server folder>")
from lucy_live import _fields
d = gzip.open(r"captures\shm\depth.gz").read()
base, mo = 0x1000, 0x8c
one, ts, ln = struct.unpack_from("<QQQ", d, base+mo)
msg = d[base+mo+24: base+mo+24+ln]
def walk(b, depth=0, off=0):
    for fn, v in _fields(b):
        if isinstance(v, tuple):
            p, n = v
            print("  "*depth + f"field {fn}: bytes len {n} @ {off+p}")
            if n < 2000 and depth < 4:
                try: walk(b[p:p+n], depth+1, off+p)
                except Exception: pass
            elif n >= 2000 and depth < 3:
                try: walk(b[p:p+n], depth+1, off+p)
                except Exception: print("  "*(depth+1) + "(opaque)")
        elif isinstance(v, bytes):
            val = struct.unpack("<d", v)[0] if len(v)==8 else struct.unpack("<f", v)[0]
            print("  "*depth + f"field {fn}: fixed {val:.4f}")
        else:
            print("  "*depth + f"field {fn}: {v}")
walk(msg)
