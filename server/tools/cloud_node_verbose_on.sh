set -e
cd /data/user/app/bin
# keep a pristine backup once
[ -f /data/lucy_local/cloud_node.orig ] || cp -p cloud_node /data/lucy_local/cloud_node.orig
if [ ! -f cloud_node.real ]; then
  mv cloud_node cloud_node.real
  printf '#!/system/bin/sh\nexport GLOG_minloglevel=0\nexec /data/user/app/bin/cloud_node.real "$@"\n' > cloud_node
  chmod 755 cloud_node
fi
cat cloud_node
kill $(pidof cloud_node.real cloud_node 2>/dev/null) 2>/dev/null || true
sleep 6
ps -o pid,ppid,args | grep cloud_node | grep -v grep
