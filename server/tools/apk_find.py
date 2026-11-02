"""Find and decompile the Trifo Home app methods that use given strings.

    python apk_find.py <regex> [out_dir]

Reads classes*.dex from the Lucy Dump apk_extract folder (parsed as data only), writes one
.java file per matching method into out_dir and prints a summary.
"""
import os
import re
import sys
import time

import ag_shim  # noqa: F401  (must come before androguard)
from androguard.core.analysis.analysis import Analysis
from androguard.core.dex import DEX
from androguard.decompiler.decompiler import DecompilerDAD
from loguru import logger

logger.remove()                       # androguard is very chatty

SRC = r"apk_extract"
pattern = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else r"<server folder>\captures\apk_src"
os.makedirs(out, exist_ok=True)

t0 = time.time()
dx = Analysis()
dexes = []
for name in sorted(os.listdir(SRC)):
    if re.fullmatch(r"classes\d*\.dex", name):
        d = DEX(open(os.path.join(SRC, name), "rb").read())
        dx.add(d)
        dexes.append(d)
dx.create_xref()
for d in dexes:
    d.set_decompiler(DecompilerDAD(d, dx))
print(f"loaded {len(dexes)} dex files in {time.time() - t0:.0f}s", flush=True)

done = set()
for sa in dx.find_strings(pattern):
    users = sorted({f"{m.class_name}->{m.name}" for _, m in sa.get_xref_from()})
    print(f"\n'{sa.get_value()}' used in:")
    for u in users[:12]:
        print("   ", u)
    for _, m in sa.get_xref_from():
        key = (m.class_name, m.name, m.descriptor)
        if key in done or m.is_external():
            continue
        done.add(key)
        try:
            src = m.get_method().get_source()
        except Exception as e:
            src = f"// decompile failed: {e}"
        fname = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{m.class_name.strip('L;').replace('/', '.')}__{m.name}") + ".java"
        with open(os.path.join(out, fname), "w", encoding="utf-8") as f:
            f.write(f"// {m.class_name}->{m.name}{m.descriptor}\n{src}\n")
print(f"\nwrote {len(done)} methods to {out}")
