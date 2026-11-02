set -e
H=/data/lucy_local/hosts
cp -p $H /data/lucy_local/hosts.bak_$(date +%Y%m%d_%H%M%S)
for d in pt.lightfieldcamera.com.cn lt.lightfieldcamera.com.cn push.lightfieldcamera.com.cn; do
  grep -q " $d\$" $H || echo "YOUR_SERVER_IP $d" >> $H
done
echo "== $H"; cat $H
echo "== /system/etc/hosts (bind-mounted view)"; cat /system/etc/hosts
ls -l /data/lucy_local/ | grep hosts
