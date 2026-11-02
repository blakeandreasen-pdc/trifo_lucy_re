B=/data/lucy_local/backup_20261013_maps
mkdir -p $B
cp -p /data/user/app/data.db $B/
cp -rp /data/user/app/lucy_map $B/
cp -p /data/user/app/room_map.png /data/user/app/rotated_room_map.png $B/
ls -laR $B
md5sum /data/user/app/data.db $B/data.db /data/user/app/lucy_map/* $B/lucy_map/*
#
