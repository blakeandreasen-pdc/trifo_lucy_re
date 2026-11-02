import re, sys
d = open(sys.argv[1], "rb").read()
types = [d[m.end()] & 0x1f for m in re.finditer(rb"\x00\x00\x00\x01", d)]
from collections import Counter
c = Counter(types)
print("bytes", len(d), "NAL counts:", dict(c))
print("first NAL types:", types[:12])
