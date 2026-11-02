r"""Copy a local file onto Lucy over SSH (stdin -> cat), then chmod +x:
    python tools\lucy_put.py <local file> <remote path>"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import lucy_live  # noqa: E402

src, dst = sys.argv[1], sys.argv[2]
cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [lucy_live.SSH_HOST,
       f"cat > {dst}.part && mv {dst}.part {dst} && chmod 755 {dst} && ls -la {dst}"]
r = subprocess.run(cmd, input=Path(src).read_bytes(), capture_output=True, timeout=120)
sys.stdout.write(r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace"))
