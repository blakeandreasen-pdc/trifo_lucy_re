#!/system/bin/sh
# watch_inputs: while Chloe presses things, log what each press looks like inside Lucy. Read-only.
#   watch_inputs.sh <seconds>   writes /data/lucy_local/inputs/ (status feed, sensor flags, signals)
S=${1:-90}
D=/data/lucy_local/inputs
mkdir -p $D
Z=/data/lucy_local/zq2
$Z /data/local/tmp/txen_driver-robot_status SUB 01 $((S * 1000)) > $D/robot_status.txt 2>&1 &
$Z /data/local/tmp/txen_driver-bot_data SUB 01 $((S * 1000)) > $D/bot_data.txt 2>&1 &
getevent -lt /dev/input/event0 > $D/event0.txt 2>&1 &
G=$!
L=$(wc -c < /data/user/app/log/manager_node.ERROR)
sleep $S
kill $G 2>/dev/null
tail -c +$L /data/user/app/log/manager_node.ERROR | grep -aE 'new signal|Mode switch' | cut -c7-170 > $D/signals.txt
echo done > $D/done
