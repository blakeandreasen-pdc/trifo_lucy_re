f=$(ls -t /data/user/app/log/cloud_node.localhost*ERROR* | head -1)
g=/data/user/app/log/guidance_node.localhost.root.log.ERROR.20210128-115257.1290
date
echo "== mode switches today"
grep -a -E 'MODE SWITCH|clean finished|low power|battery low|recharge|RECHARGE' $f | grep -a 'E1015 1[12]:' | cut -c1-170
echo "== planner: last transitions"
grep -a -E 'PLANNER_.*->' $g | grep -a 'E1015 1[12]:' | cut -c32-140 | tail -14
echo "== planner: reasons"
grep -a -i -E 'finish|no frontier|no more|explore done|coverage|low batt|recharge|unreachable|blocked' $g | grep -a 'E1015 1[12]:' | cut -c1-170 | tail -10
echo "== battery"
grep -a -A16 'all_info:' $f | grep -a battery | tail -3
echo "== audio"
ls -la /data/user/app/audio | head -30
du -sh /data/user/app/audio
