ls /dev/video* 2>/dev/null | tr '\n' ' '; echo
ls /data/user/app/node_config/ | grep -i -E 'camera|sensor'
grep -o -i -E '"[a-z_]*(camera|tof|cam_|video|device|rear|back|stream)[a-z_]*" *: *[^,{]*' /data/user/app/node_config/config_camera_node.json 2>/dev/null | sort -u | head -40
