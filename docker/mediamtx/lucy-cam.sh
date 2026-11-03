#!/bin/sh
# MediaMTX runOnDemand for path "lucy" (no root needed on the robot).
# Wakes Lucy's RTMP push (RTMP_THROB + STREAM_CONTROL 1 every 2.5 s via the
# capture server's /api/rxcmd), then relays her app-name/<id> stream into "lucy".
# MediaMTX kills this when the last reader leaves (runOnDemandCloseAfter).
API=http://lucy:8080/api/rxcmd
post() {
  wget -q -O /dev/null --header="Content-Type: application/json" --post-data="$1" "$API"
}
beat() {
  while :; do
    post '{"cmd":"RTMP_THROB","data":"","key":"10","wait":0}'
    post '{"cmd":"STREAM_CONTROL","data":"1","key":"10","wait":0}'
    sleep 2.5
  done
}
beat & BEAT=$!
FF=""
trap 'kill $BEAT $FF 2>/dev/null; exit 0' INT TERM

SRC=""
for i in $(seq 1 30); do
  SRC=$(wget -q -O - http://127.0.0.1:9997/v3/paths/list | grep -o '"name":"app-name/[^"]*"' | head -1 | cut -d'"' -f4)
  [ -n "$SRC" ] && break
  sleep 1
done
if [ -z "$SRC" ]; then echo "lucy-cam: robot never published"; kill $BEAT; exit 1; fi

# The path can be listed a moment before her publish is ready (404), so retry the relay.
for i in $(seq 1 20); do
  ffmpeg -hide_banner -loglevel warning -rtsp_transport tcp -i "rtsp://127.0.0.1:8554/$SRC" \
    -c copy -f rtsp "rtsp://127.0.0.1:8554/lucy" &
  FF=$!
  wait $FF
  sleep 1
done
kill $BEAT 2>/dev/null
