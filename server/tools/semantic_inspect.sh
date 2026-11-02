cd /data/user/app
echo "== labels"
cat dl/label_color_map_16_classes.txt
echo
echo "== semantic_instance_info schema"
sqlite3 data.db '.schema semantic_instance_info'
echo "== counts by type (map 1)"
sqlite3 data.db "select type, count(*) from semantic_instance_info where map_id = 1 group by type order by 2 desc" 2>&1
echo "== sample rows"
sqlite3 data.db "select * from semantic_instance_info where map_id = 1 limit 5" 2>&1 | cut -c1-200
