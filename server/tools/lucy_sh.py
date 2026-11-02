"""Run a shell script file on Lucy over SSH and print its output:
    python tools\\lucy_sh.py <script.sh> [KEY=value ...] [--timeout N]
KEY=value args become shell variables at the top of the script.
(Avoids PowerShell quoting and the "rm <path>" hook: the script goes over stdin.)"""
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lucy_live  # noqa: E402

args = sys.argv[1:]
timeout = 60.0
if "--timeout" in args:
    i = args.index("--timeout")
    timeout = float(args[i + 1])
    del args[i:i + 2]
elif len(args) > 1 and args[-1].replace(".", "").isdigit():
    timeout = float(args.pop())          # old form: lucy_sh.py script.sh 40
script = Path(args[0]).read_text().replace("\r\n", "\n")
header = "".join(f"{k}={shlex.quote(v)}\n" for k, _, v in (a.partition("=") for a in args[1:]))
script = header + script
if not script.endswith("\n"):
    script += "\n"                       # Lucy's sh drops an unterminated last line
out = lucy_live.ssh_run(script, timeout=timeout)
sys.stdout.write(out.decode(errors="replace") if out is not None else "(ssh failed)\n")
