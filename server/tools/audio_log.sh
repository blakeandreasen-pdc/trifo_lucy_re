cd /data/user/app/log
for f in sensor_node.ERROR cloud_node.ERROR; do
  echo "== $f"
  tail -c 400000 $f | grep -i -E 'audio|talk|capture|stream_on|mic|voice' | tail -${1:-30}
done
