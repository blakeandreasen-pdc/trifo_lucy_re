d=/data/lucy_local/sp
mkdir -p $d && cd $d && for f in h_* c_*; do [ -e "$f" ] && : > "$f"; done
cd /dev/shm
H=TrifoSemaphore_lucy_camera-image_data_h264
C=TrifoSemaphore_lucy_camera-cg_encode_data
i=0
while [ $i -lt 250 ]; do
  for s in 0 1 2; do
    dd if=$H bs=4096 skip=$((1 + s * 1024)) count=1 of=$d/h_${i}_$s 2>/dev/null
    dd if=$C bs=4096 skip=$((1 + s * 256)) count=1 of=$d/c_${i}_$s 2>/dev/null
  done
  i=$((i + 1))
done
cd $d && md5sum h_* c_* | sort | uniq -w32 | awk '{print $2}' > keep.txt
tar cf - $(cat keep.txt) | gzip -1 > /data/lucy_local/sp.tgz
wc -l < keep.txt
