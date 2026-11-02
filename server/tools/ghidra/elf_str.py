"""Print C strings at virtual addresses in an ELF (e.g. Ghidra DAT_ addresses).
    /opt/tools/venv/bin/python elf_str.py <elf> <hex addr> [<hex addr> ...] [--base 0x100000]
Ghidra loads ARM64 shared objects at 0x100000, so pass --base 0x100000 for its addresses."""
import struct
import sys

args = [a for a in sys.argv[2:] if not a.startswith("--")]
base = int(sys.argv[sys.argv.index("--base") + 1], 16) if "--base" in sys.argv else 0
args = [a for a in args if a != hex(base) and a != sys.argv[sys.argv.index("--base") + 1]] if base else args
d = open(sys.argv[1], "rb").read()
shoff, = struct.unpack_from("<Q", d, 0x28)
phoff, = struct.unpack_from("<Q", d, 0x20)
phentsize, phnum = struct.unpack_from("<HH", d, 0x36)
segs = []
for i in range(phnum):
    p_type, _, p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<IIQQQQ", d, phoff + i * phentsize)
    if p_type == 1:
        segs.append((p_vaddr, p_offset, p_filesz))
for a in args:
    va = int(a, 16) - base
    for v, o, sz in segs:
        if v <= va < v + sz:
            off = o + va - v
            s = d[off:d.index(b"\0", off)]
            print(f"{a}: {s!r}")
            break
    else:
        print(f"{a}: (not in a loaded segment)")
