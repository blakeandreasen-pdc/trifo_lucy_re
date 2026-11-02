cd /dev/shm
for f in TrifoSemaphore_lucy_camera-image_data_h264 TrifoSemaphore_lucy_camera-cg_encode_data; do
  echo "== $f"
  sz=$(wc -c < $f)
  for s in 0 1 2 3; do
    off=$((s * 1024))   # 4 MiB slots in 4 KiB blocks
    [ $((off * 4096)) -ge $sz ] && break
    echo "-- slot $s"
    dd if=$f bs=4096 skip=$off count=1 2>/dev/null | od -A d -t x1 | head -6
  done
done
# small-stride view of cg file (3 MB may be 3 x 1 MiB)
echo "== cg 1MiB strides"
for s in 0 1 2; do dd if=TrifoSemaphore_lucy_camera-cg_encode_data bs=4096 skip=$((s*256)) count=1 2>/dev/null | od -A d -t x1 | head -3; done
