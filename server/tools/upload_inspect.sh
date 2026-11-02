cd /data/user/app
sqlite3 data.db '.schema tb_split_log'
sqlite3 data.db 'select count(*), sum(upload_flag=0), max(create_time) from tb_split_log'
sqlite3 data.db 'select * from tb_split_log order by create_time desc limit 5'
echo "== /data/tmp/upload"
ls -la /data/tmp/upload/ 2>&1 | head
echo "== config"
grep -o -E '"(clean_auto_upload[a-z_]*|upload[a-z_]*|record[a-z_]*|aws[a-z_]*)" *: *[^,]*' node_config/config_cloud_node.json | head -20
