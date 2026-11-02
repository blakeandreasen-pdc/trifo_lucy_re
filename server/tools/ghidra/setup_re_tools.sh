#!/bin/sh
# jadx + Ghidra into /opt/tools (run as root):  wsl -u root -e sh /mnt/c/Claude/wsl_toolbox/setup_re_tools.sh
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq openjdk-21-jdk-headless >/dev/null
cd /opt/tools
latest() {  # $1 = owner/repo, $2 = regex for asset name -> prints download URL
  wget -qO- "https://api.github.com/repos/$1/releases/latest" | grep -o '"browser_download_url": *"[^"]*"' \
    | sed 's/.*"\(http[^"]*\)"/\1/' | grep -E "$2" | head -1
}
if [ ! -x /opt/tools/jadx/bin/jadx ]; then
  url=$(latest skylot/jadx 'jadx-[0-9.]+\.zip$'); echo "jadx: $url"
  wget -q -O jadx.zip "$url" && rm -rf jadx && unzip -q jadx.zip -d jadx && rm jadx.zip
fi
if ! ls -d /opt/tools/ghidra_* >/dev/null 2>&1; then
  url=$(latest NationalSecurityAgency/ghidra 'ghidra_.*_PUBLIC_.*\.zip$'); echo "ghidra: $url"
  wget -q -O ghidra.zip "$url" && unzip -q ghidra.zip && rm ghidra.zip
fi
ln -sfn "$(ls -d /opt/tools/ghidra_* | head -1)" /opt/tools/ghidra
ln -sf /opt/tools/jadx/bin/jadx /usr/local/bin/jadx
ln -sf /opt/tools/ghidra/support/analyzeHeadless /usr/local/bin/ghidra-headless
chmod -R a+rX /opt/tools
jadx --version
ls /opt/tools
