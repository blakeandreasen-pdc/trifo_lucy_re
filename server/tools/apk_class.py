"""Decompile whole classes from the Trifo Home app to a .java file each.

    python apk_class.py <class descriptor> [<class descriptor> ...]     e.g. Lr2/f;
"""
import os
import re
import sys

import ag_shim  # noqa: F401
from androguard.core.analysis.analysis import Analysis
from androguard.core.dex import DEX
from androguard.decompiler.decompiler import DecompilerDAD
from loguru import logger

logger.remove()
SRC = r"apk_extract"
OUT = r"<server folder>\captures\apk_src"
os.makedirs(OUT, exist_ok=True)

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

for want in sys.argv[1:]:
    for d in dexes:
        for c in d.get_classes():
            if c.get_name() == want:
                path = os.path.join(OUT, "CLASS_" + re.sub(r"[^A-Za-z0-9_.$-]", "_", want.strip("L;").replace("/", ".")) + ".java")
                try:
                    src = c.get_source()
                except Exception as e:
                    src = "\n".join(f"// {m.get_name()} failed: {e}" for m in c.get_methods())
                open(path, "w", encoding="utf-8").write(src)
                print("wrote", path, len(src))
