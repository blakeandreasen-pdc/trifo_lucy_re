#!/bin/sh
# Shared Python toolbox for WSL (run as root):  wsl -u root -e sh /mnt/c/Claude/wsl_toolbox/setup_venv.sh
set -e
mkdir -p /opt/tools
[ -x /opt/tools/venv/bin/python ] || python3 -m venv /opt/tools/venv
/opt/tools/venv/bin/pip install -q --upgrade pip
/opt/tools/venv/bin/pip install -q numpy scipy capstone androguard lz4 protobuf pillow opencv-python-headless
chmod -R a+rX /opt/tools
/opt/tools/venv/bin/python - <<'EOF'
import numpy, scipy, capstone, androguard, lz4, cv2, PIL
print("numpy", numpy.__version__, "| capstone", capstone.__version__, "| opencv", cv2.__version__,
      "| androguard", androguard.__version__)
EOF
