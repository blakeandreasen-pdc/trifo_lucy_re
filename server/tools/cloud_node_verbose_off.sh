set -e
cd /data/user/app/bin
if [ -f cloud_node.real ]; then
  mv -f cloud_node.real cloud_node
fi
head -c 4 cloud_node | od -c | head -1
kill $(pidof cloud_node.real cloud_node 2>/dev/null) 2>/dev/null || true
sleep 6
ps -o pid,ppid,args | grep cloud_node | grep -v grep
