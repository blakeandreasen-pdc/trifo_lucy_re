f=$(ls -t /data/user/app/log/cloud_node.localhost*ERROR* | head -1)
date
grep -a -E 'MODE SWITCH|BLOWER:|Sweep Task' $f | grep -a 'E1015 11:' | cut -c1-170
grep -a -A16 'all_info:' $f | grep -a -E '"blower"|clean_state|battery' | tail -3
grep -a -E 'PLANNER_.*->' /data/user/app/log/guidance_node.localhost.root.log.ERROR.20210128-115257.1290 | cut -c1-120 | tail -3
