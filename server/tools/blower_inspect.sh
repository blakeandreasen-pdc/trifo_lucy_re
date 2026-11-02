cd /data/user/app
echo "== cloud log: blower"
grep -a -h -i -E 'blower|BLOWER' $(ls -t log/cloud_node.localhost*ERROR* | head -1) | tail -6 | cut -c1-170
echo "== guidance/sensor log: blower/fan/suction"
grep -a -h -i -E 'blower|suction|fan|vacuum' log/guidance_node.localhost.root.log.ERROR.20210128-115257.1290 | tail -6 | cut -c1-170
grep -a -h -i -E 'blower|suction|fan|vacuum' log/sensor_node.localhost.root.log.ERROR.20210128-115255.1289 | tail -6 | cut -c1-170
echo "== config: blower limits"
grep -h -o -E '"[a-z_]*blower[a-z_]*" *: *[^,]*' node_config/*.json | sort -u
echo "== db"
sqlite3 data.db "select key, value from system_config where key like '%blower%'"
