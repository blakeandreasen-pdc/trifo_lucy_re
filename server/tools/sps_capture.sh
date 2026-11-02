out=/data/lucy_local/sps_strace.txt
timeout 45 strace -f -e trace=recvfrom,recvmsg,read -s 1200 -x -p $(pidof cloud_node) -o $out 2>/dev/null
echo "lines: $(wc -l < $out)"
grep -c -E 'x67\\x(4d|64|42)|x00\\x00\\x00\\x01\\x67' $out
grep -o 'x00\\x00\\x00\\x01\\x67[^"]*' $out | head -4 | cut -c1-900
