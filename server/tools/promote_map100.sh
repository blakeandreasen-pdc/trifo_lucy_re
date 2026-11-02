# Promote Lucy's "preview" map (map100) to her saved map (map1) - the app's old
# "refresh map" button. Run on Lucy, e.g. from the Surface:
#   Get-Content tools\promote_map100.sh -Raw | ssh <opts> root@<lucy> sh -s
#
# When she runs:
#   - saved map has no zones (map_path empty) -> she updates map1 herself.
#   - saved map has zones -> she leaves map1 alone and saves the run as map100
#     ("has map path, save back up map"). Use this script to accept map100.
# Map100 is tracked against map1, so map1's zones/room names keep their
# coordinates and are left as they are. Rooms + recognised objects come from map100.
set -e
cd /data/user/app
sqlite3 data.db "select count(*) from map_list where id=100" | grep -q '^1$' || { echo "no map100 to promote"; exit 1; }
B=/data/lucy_local/backup_$(date +%Y%m%d_%H%M%S)
mkdir -p $B
cp -p data.db $B/ && cp -rp lucy_map $B/
echo "backup: $B"
cp -p lucy_map/pose_graph_map100.pbstream lucy_map/pose_graph_map.pbstream.new
mv lucy_map/pose_graph_map.pbstream.new lucy_map/pose_graph_map.pbstream
sqlite3 data.db <<'SQL'
BEGIN;
UPDATE map_list SET
  charger_pose      = (SELECT charger_pose      FROM map_list WHERE id=100),
  map_update_time   = (SELECT map_update_time   FROM map_list WHERE id=100),
  room_segment_edited = (SELECT room_segment_edited FROM map_list WHERE id=100),
  map_rows          = (SELECT map_rows          FROM map_list WHERE id=100),
  map_cols          = (SELECT map_cols          FROM map_list WHERE id=100),
  rotated_map_rows  = (SELECT rotated_map_rows  FROM map_list WHERE id=100),
  rotated_map_cols  = (SELECT rotated_map_cols  FROM map_list WHERE id=100),
  map_rotation_angle= (SELECT map_rotation_angle FROM map_list WHERE id=100),
  map_cell_size     = (SELECT map_cell_size     FROM map_list WHERE id=100),
  map_max_point     = (SELECT map_max_point     FROM map_list WHERE id=100),
  beauty_map        = (SELECT beauty_map        FROM map_list WHERE id=100)
WHERE id=1;
DELETE FROM room_segmentation_info WHERE map_id=1;
INSERT INTO room_segmentation_info SELECT 1, room_id, selected, room_type, room_type_id, room_name, contour, seed, rotation_angle, rotated_contour, rotated_seed FROM room_segmentation_info WHERE map_id=100;
DELETE FROM semantic_instance_info WHERE map_id=1;
INSERT INTO semantic_instance_info SELECT 1, id, type, name, contour, state FROM semantic_instance_info WHERE map_id=100;
COMMIT;
SQL
echo "== after"
md5sum lucy_map/*
sqlite3 data.db "select id,name,map_update_time,map_rows,map_cols from map_list; select map_id,path_type,count(*) from map_path group by map_id,path_type;"
OLD=$(pidof cloud_node)
kill $OLD
sleep 8
echo "cloud_node: $OLD -> $(pidof cloud_node)"
#
