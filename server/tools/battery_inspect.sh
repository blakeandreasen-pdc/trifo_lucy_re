f=$(ls -t /data/user/app/log/cloud_node.localhost*ERROR* | head -1)
date
echo "== mode switches since 23:00 UTC yesterday"
grep -a -E 'MODE SWITCH' $f | grep -a -E 'E1014 2[3]|E1015' | cut -c1-160
echo "== battery in all_info (last few)"
grep -a -A16 'all_info:' $f | grep -a -E 'battery' | tail -5
echo "== any battery/charge lines"
grep -a -i -E 'battery|charg' $f | grep -a -v -E 'MODE SWITCH|charger pose|charger pos' | tail -8 | cut -c1-170
