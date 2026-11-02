import sys, types
for name in ("lxml", "lxml.etree", "lxml.sax"):
    m = types.ModuleType(name)
    sys.modules[name] = m
sys.modules["lxml"].etree = sys.modules["lxml.etree"]
sys.modules["lxml"].sax = sys.modules["lxml.sax"]
class _Dummy:  # placeholders for names androguard references at import time
    def __init__(self, *a, **k): pass
for attr in ("Element", "SubElement", "tostring", "fromstring", "ElementTree", "XMLParser", "_Element", "QName", "XMLSyntaxError"):
    setattr(sys.modules["lxml.etree"], attr, _Dummy)
setattr(sys.modules["lxml.sax"], "ElementTreeContentHandler", _Dummy)
try:
    from androguard.core.dex import DEX
    print("dex import ok")
    from androguard.decompiler.decompile import DvMachine
    print("decompiler import ok")
except Exception as e:
    import traceback; traceback.print_exc()
