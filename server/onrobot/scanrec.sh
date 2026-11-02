#!/system/bin/sh
# scanrec: record a 3D scan on Lucy herself, needing no server or Wi-Fi once started.
#   scanrec.sh <name> <seconds> [rgb_every_s]
# Sends manager_node the same CLOUD_START_STREAM signal (16) cloud_node sends, runs depthdump to
# /data/lucy_local/scans/<name>/, records the 100 Hz angle feed, then CLOUD_STOP_STREAM (17). Stops
# early if /data has under 400 MB free. Start it detached so it outlives SSH:
#   nohup sh /data/lucy_local/scanrec.sh x 120 5 >/dev/null 2>&1 &
NAME=$1; SECS=$2; RGB=${3:-5}
L=/data/lucy_local
D=$L/scans/$NAME
mkdir -p $D
M=/data/local/tmp/TrifoIPC_manager_node_REQ
echo "start $(date +%T) up $(cut -d' ' -f1 /proc/uptime)" > $D/rec.log
$L/zq2 $M DEALER @@$((67300000 + $$)):08021a0512030a0110 800 >> $D/rec.log 2>&1
sleep 3
$L/zq2 /data/local/tmp/txen_driver-bot_data SUB 01 $((SECS * 1000)) > $D/angles.txt 2>&1 &
A=$!
$L/depthdump $SECS $RGB 25 > $D/stream.bin 2>> $D/rec.log &
P=$!
while kill -0 $P 2>/dev/null; do
  FREE=$(df /data | tail -1 | awk '{print $4}')
  if [ "$FREE" -lt 400000 ] 2>/dev/null; then echo "low space $FREE KB" >> $D/rec.log; kill $P; fi
  sleep 5
done
kill $A 2>/dev/null
$L/zq2 $M DEALER @@$((67310000 + $$)):08021a0512030a0111 800 >> $D/rec.log 2>&1
echo "end $(date +%T) up $(cut -d' ' -f1 /proc/uptime) size $(ls -l $D/stream.bin | awk '{print $5}')" >> $D/rec.log
