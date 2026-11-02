import re
s = open(r"<server folder>\captures\apk_src\CLASS_r2.f.java", encoding="utf-8").read()
# split into methods and pull key/cmd/data hints from each
for m in re.finditer(r"public void (\w+)\(([^)]*)\)\s*\{(.*?)\n    \}", s, re.S):
    body = m.group(3)
    keys = re.findall(r'setKey\("([^"]*)"\)', body)
    cmds = re.findall(r'setCmd\("([^"]*)"\)', body)
    if not cmds:
        continue
    data = re.findall(r'setData\(([^;]*)\);', body)
    print(f"{m.group(1):6s} key={','.join(keys):4s} cmd={','.join(cmds):34s} args=({m.group(2)[:40]}) data={'; '.join(d[:60] for d in data)}")
