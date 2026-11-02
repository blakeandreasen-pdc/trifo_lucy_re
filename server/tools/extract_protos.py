"""
Rebuild .proto definitions from FileDescriptorProto blobs embedded in Lucy's
shared libraries (protobuf's generated code keeps the serialized descriptor).

    python tools/extract_protos.py <lib.so> [<lib.so> ...] > lucy_protos.proto

Pure stdlib: a minimal protobuf wire parser walks the descriptor messages.
"""
import re
import sys

TYPES = {1: "double", 2: "float", 3: "int64", 4: "uint64", 5: "int32", 6: "fixed64",
         7: "fixed32", 8: "bool", 9: "string", 10: "group", 11: "message", 12: "bytes",
         13: "uint32", 14: "enum", 15: "sfixed32", 16: "sfixed64", 17: "sint32", 18: "sint64"}
LABELS = {1: "optional", 2: "required", 3: "repeated"}


def varint(b, p):
    r = s = 0
    while True:
        if p >= len(b):
            raise ValueError("eof")
        c = b[p]
        p += 1
        r |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return r, p


def fields(b):
    """Yield (field, wire_type, value) - strict: raises on malformed input."""
    p = 0
    while p < len(b):
        tag, p = varint(b, p)
        fn, wt = tag >> 3, tag & 7
        if fn == 0:
            raise ValueError("field 0")
        if wt == 0:
            v, p = varint(b, p)
        elif wt == 1:
            v = b[p:p + 8]; p += 8
        elif wt == 5:
            v = b[p:p + 4]; p += 4
        elif wt == 2:
            n, p = varint(b, p)
            if p + n > len(b):
                raise ValueError("overrun")
            v = b[p:p + n]; p += n
        else:
            raise ValueError("wire type")
        yield fn, wt, v


def parse_file_descriptor(blob):
    """Parse FileDescriptorProto fields; returns (consumed_len, info) for the
    longest prefix that parses cleanly as a plausible descriptor."""
    info = {"name": None, "package": None, "deps": [], "messages": [], "enums": []}
    p = 0
    good = 0
    while p < len(blob):
        try:
            tag, q = varint(blob, p)
            fn, wt = tag >> 3, tag & 7
            if fn not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12) or wt not in (0, 2):
                break
            if wt == 2:
                n, q = varint(blob, q)
                if q + n > len(blob):
                    break
                v = blob[q:q + n]
                q += n
            else:
                v, q = varint(blob, q)
            if fn == 1: info["name"] = v.decode()
            elif fn == 2: info["package"] = v.decode()
            elif fn == 3: info["deps"].append(v.decode())
            elif fn == 4: info["messages"].append(parse_message(v))
            elif fn == 5: info["enums"].append(parse_enum(v))
            elif fn == 12: info["syntax"] = v.decode()
            p = q
            good = p
        except (ValueError, UnicodeDecodeError):
            break
    return good, info


def parse_enum(b):
    e = {"name": "", "values": []}
    for fn, wt, v in fields(b):
        if fn == 1:
            e["name"] = v.decode()
        elif fn == 2:
            name, num = "", 0
            for f2, w2, v2 in fields(v):
                if f2 == 1: name = v2.decode()
                elif f2 == 2: num = v2 if v2 < 1 << 31 else v2 - (1 << 64)
            e["values"].append((name, num))
    return e


def parse_message(b):
    m = {"name": "", "fields": [], "nested": [], "enums": []}
    for fn, wt, v in fields(b):
        if fn == 1:
            m["name"] = v.decode()
        elif fn == 2:
            f = {"name": "", "number": 0, "label": 1, "type": 9, "type_name": "", "default": None}
            for f2, w2, v2 in fields(v):
                if f2 == 1: f["name"] = v2.decode()
                elif f2 == 3: f["number"] = v2
                elif f2 == 4: f["label"] = v2
                elif f2 == 5: f["type"] = v2
                elif f2 == 6: f["type_name"] = v2.decode()
                elif f2 == 7: f["default"] = v2.decode()
            m["fields"].append(f)
        elif fn == 3:
            m["nested"].append(parse_message(v))
        elif fn == 4:
            m["enums"].append(parse_enum(v))
    return m


def fmt_enum(e, ind):
    out = [f"{ind}enum {e['name']} {{"]
    out += [f"{ind}  {n} = {v};" for n, v in e["values"]]
    return out + [f"{ind}}}"]


def fmt_message(m, ind=""):
    out = [f"{ind}message {m['name']} {{"]
    for e in m["enums"]:
        out += fmt_enum(e, ind + "  ")
    for n in m["nested"]:
        out += fmt_message(n, ind + "  ")
    for f in m["fields"]:
        t = f["type_name"].lstrip(".") if f["type"] in (11, 14) else TYPES.get(f["type"], "?")
        d = f" [default = {f['default']}]" if f["default"] is not None else ""
        out.append(f"{ind}  {LABELS.get(f['label'], '')} {t} {f['name']} = {f['number']}{d};")
    return out + [f"{ind}}}"]


def main():
    seen = set()
    for path in sys.argv[1:]:
        data = open(path, "rb").read()
        # A FileDescriptorProto starts with field 1 (name): 0x0A <len> "...proto"
        for m in re.finditer(rb"\x0a([\x05-\x7f])([\x20-\x7e]{1,120}?\.proto)", data):
            if m.group(1)[0] != len(m.group(2)):
                continue
            name = m.group(2).decode()
            if name in seen:
                continue
            used, info = parse_file_descriptor(data[m.start():m.start() + 200000])
            if not info["messages"] and not info["enums"]:
                continue
            seen.add(name)
            print(f"// ===== {name}  (from {path.split(chr(92))[-1]}, {used} bytes)")
            if info["package"]:
                print(f"// package {info['package']}")
            for d in info["deps"]:
                print(f'// import "{d}";')
            for e in info["enums"]:
                print("\n".join(fmt_enum(e, "")))
            for msg in info["messages"]:
                print("\n".join(fmt_message(msg)))
            print()


if __name__ == "__main__":
    main()
