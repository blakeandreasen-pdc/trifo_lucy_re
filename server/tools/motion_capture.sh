# Record what sensor_node receives (ZeroMQ commands from guidance) and writes (to the MCU serial)
# for SECS seconds, in the background. Output: /data/lucy_local/motion_strace.txt
SECS=${SECS:-120}
out=/data/lucy_local/motion_strace.txt
P=$(pidof sensor_node)
ls -l /proc/$P/fd 2>/dev/null | grep -E 'ttyS1' 
nohup timeout $SECS strace -f -tt -e trace=recvfrom,write -s 300 -x -p $P -o $out >/dev/null 2>&1 &
echo started capture for $SECS s
