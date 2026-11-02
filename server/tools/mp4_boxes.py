import struct, sys
d = open(sys.argv[1], "rb").read()
d = d[d.find(b"\r\n\r\n")+4:]
open(sys.argv[1].replace(".raw", ""), "wb").write(d)
i, kinds = 0, []
while i + 8 <= len(d):
    n, k = struct.unpack_from(">I4s", d, i)
    if n < 8: break
    kinds.append(k.decode()); i += n
from collections import Counter
print(len(d), "bytes; top-level boxes:", kinds[:6], Counter(kinds))
