"""Dump the QLCloud packet map (g_ql_packet_map, 24-byte entries) from libtrifo_core_cloud.so.
    python ql_packet_map.py <lib.so> [vaddr=0x228108] [count=26]"""
import struct
import sys

d = open(sys.argv[1], "rb").read()
va = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x228108
count = int(sys.argv[3]) if len(sys.argv) > 3 else 26
phoff, = struct.unpack_from("<Q", d, 0x20)
phentsize, phnum = struct.unpack_from("<HH", d, 0x36)
for i in range(phnum):
    p_type, _, p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<IIQQQQ", d, phoff + i * phentsize)
    if p_type == 1 and p_vaddr <= va < p_vaddr + p_filesz:
        off = p_offset + va - p_vaddr
        break
for k in range(count):
    e = d[off + k * 24: off + k * 24 + 24]
    print(f"type {k:#04x}: opcode {struct.unpack_from('<H', e)[0]:#06x}   raw {e.hex(' ')}")
