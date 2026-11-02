import re
d = open(r"captures\qlcloud_tail.bin", "rb").read()
txt = re.sub(rb"\x1b\[[0-9;]*m", b"", d).decode("latin1")
lines = [l for l in txt.splitlines() if l.strip()]
for l in lines[-40:]:
    print(l[:220])
