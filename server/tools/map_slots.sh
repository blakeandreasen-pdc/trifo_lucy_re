# Named map "slots" for taking Lucy between places (home, a second house...). Run on Lucy via
#   python tools\lucy_sh.py tools\map_slots.sh MODE=list|save|load|blank NAME=<slot>
# A slot = lucy_map/pose_graph_map.pbstream + the rows of map_list, map_path (no-go zones),
# room_segmentation_info and semantic_instance_info (all maps' rows, normally just map 1).
# load/blank first auto-save the current map as slot "_before_<time>", then restart cloud_node.
# blank = no saved map at all (like a new robot) so her next run builds a fresh one - EXPERIMENTAL.
# delete = delete a slot for good (Chloe, 2026-10-25); _guard can't be deleted.
# Automatic backups (_before_*, _blanked_*) are pruned to the newest $KEEP_AUTO of each kind.
set -e
APP=/data/user/app
SLOTS=/data/lucy_local/maps
TABLES="map_list map_path room_segmentation_info semantic_instance_info"
KEEP_AUTO=5
mkdir -p $SLOTS
cd $APP

save_slot() {
  d=$SLOTS/$1
  mkdir -p $d
  cp -p lucy_map/pose_graph_map.pbstream $d/ 2>/dev/null || echo "(no pbstream)"
  : > $d/rows.sql
  for t in $TABLES; do
    sqlite3 -cmd ".mode insert $t" data.db "select * from $t" >> $d/rows.sql
  done
  sqlite3 data.db "select id,name,map_update_time from map_list" > $d/info.txt
  date > $d/saved_at.txt
  echo "saved slot $1: $(wc -l < $d/rows.sql) rows, $(ls -s $d/pose_graph_map.pbstream 2>/dev/null)"
}

prune_auto() {
  for pat in "_before_*" "_blanked_pbstream_*"; do
    ls -dt $SLOTS/$pat 2>/dev/null | tail -n +$((KEEP_AUTO + 1)) | while read old; do rm -rf "$old"; done
  done
  rm -rf $SLOTS/_trash
}

clear_tables() {
  for t in $TABLES; do echo "DELETE FROM $t;"; done
}

restart_cloud() {
  OLD=$(pidof cloud_node)
  kill $OLD
  sleep 8
  echo "cloud_node: $OLD -> $(pidof cloud_node)"
}

case "$MODE" in
  list)
    for d in $SLOTS/*/; do
      [ -d "$d" ] || continue
      echo "== $(basename $d)  saved $(cat $d/saved_at.txt)  $(tr '\n' ' ' < $d/info.txt)"
    done
    echo "== current: $(sqlite3 data.db 'select id,name,map_update_time from map_list' | tr '\n' ' ')"
    ;;
  tsv)
    # for the control page: name <tab> saved-at <tab> map_list rows <tab> map file bytes (one line per slot)
    for d in $SLOTS/*/; do
      [ -d "$d" ] || continue
        printf '%s\t%s\t%s\t%s\n' "$(basename $d)" "$(cat $d/saved_at.txt)" "$(tr '\n' ' ' < $d/info.txt)" "$(stat -c %s $d/pose_graph_map.pbstream 2>/dev/null || echo 0)"
    done
    printf 'current\t\t%s\n' "$(sqlite3 data.db 'select id,name,map_update_time from map_list' | tr '\n' ' ')"
    ;;
  save)
    [ -n "$NAME" ] || { echo "NAME= needed"; exit 1; }
    save_slot "$NAME"
    case "$NAME" in _before_*) prune_auto ;; esac
    ;;
  load)
    [ -f "$SLOTS/$NAME/rows.sql" ] || { echo "no slot $NAME"; exit 1; }
    save_slot "_before_$(date +%Y%m%d_%H%M%S)"
    prune_auto
    { echo "BEGIN;"; clear_tables; cat $SLOTS/$NAME/rows.sql; echo "COMMIT;"; } | sqlite3 data.db
    if [ -f $SLOTS/$NAME/pose_graph_map.pbstream ]; then
      cp -p $SLOTS/$NAME/pose_graph_map.pbstream lucy_map/pose_graph_map.pbstream.new
      mv lucy_map/pose_graph_map.pbstream.new lucy_map/pose_graph_map.pbstream
    fi
    echo "loaded slot $NAME: $(sqlite3 data.db 'select id,name,map_update_time from map_list' | tr '\n' ' ')"
    restart_cloud
    ;;
  delete)
    [ -n "$NAME" ] && [ "$NAME" != "_guard" ] && [ -d "$SLOTS/$NAME" ] || { echo "can't delete slot $NAME"; exit 1; }
    rm -rf "$SLOTS/$NAME"
    echo "deleted slot $NAME"
    ;;
  blank)
    save_slot "_before_$(date +%Y%m%d_%H%M%S)"
    prune_auto
    { echo "BEGIN;"; clear_tables; echo "COMMIT;"; } | sqlite3 data.db
    mv lucy_map/pose_graph_map.pbstream $SLOTS/_blanked_pbstream_$(date +%Y%m%d_%H%M%S)
    echo "blanked: no saved map"
    restart_cloud
    ;;
  *)
    echo "MODE=list|tsv|save|load|blank"
    ;;
esac
