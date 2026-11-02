# Maps

There are three different things called "the map", and only the first two turned out to matter:

1. **Live map:** a grid in shared memory, read over SSH.
2. **Saved map:** a Google Cartographer `.pbstream` file on the robot.
3. **Upload file:** the `.ogm` she tries to send to the cloud after a run. Its grid encoding was never decoded. That work is parked, because the other two give us everything we need.

## Live map

`server/map_reader.py` reads `/dev/shm/TrifoSemaphore_mapper-multi_layer_map` and `TrifoSemaphore_visual_mapper-multi_layer_map`, skipping an 8 KiB header. Pose converts to grid position as `row = (max_x - x) / cell_size`, `col = (max_y - y) / cell_size`.

Her pose comes from a SUB connection to `mapper-global_pose` (`server/pose_feed.py`). An earlier method using `strace` on `slam_node` froze her tracker on every map refresh, so don't use that one.

Until she relocalises at the start of a run, the live map is a fresh frame with the dock near the origin, so a displayed map can jump once she relocalises.

## Saved maps

Files live in `lucy_map/` on the robot, and `/data/user/app/data.db` (SQLite) holds `map_list`, `map_path` (zones), `room_segmentation_info` and `semantic_instance_info`.

- `pose_graph_map.pbstream` is the main map.
- `pose_graph_map100.pbstream` is a throwaway. Runs she doesn't count as finished save there, and it's **deleted when the next run starts or a different map is loaded**.

### When she updates the main map

Her log messages describe this rule: at the end of a run, if the main map has no `map_path` rows she updates it herself. If it has zones, she keeps it frozen and saves the run as map 100.

We haven't fully tested how that rule plays out. It would mean that adding a keep-out zone freezes the main map, so new rooms she finds never get kept.

Restarting `cloud_node` puts her into NeedReloc, and the next run starts with a relocalisation spin. If that fails, she drops the zones and does a normal full clean. So avoid restarts where you can. Loading a map slot does one.

### File format

`.pbstream` is an 8-byte magic number (`db01f55b7b1f1d7b`), then chunks of a `u64` length plus a gzipped protobuf:

| Chunk | Contents |
|-------|----------|
| 0 | header `{1: format version}` |
| 1 | pose_graph (field 1) `{constraint (2), trajectory (4)}` |
| 2 | all_trajectory_builder_options (field 2), one entry per trajectory |
| 3 onward | nodes (field 4), and Lucy's multi-layer submaps (field 10) |

- Trajectory: `{node (1) {timestamp (1), pose (5), node_index (7)}, submap (2) {pose (1), submap_index (2)}, trajectory_id (3)}`
- Constraint: `{submap_id (1), node_id (2), relative_pose (3), tag (5; 1 = INTER_SUBMAP, absent = INTRA), translation_weight (6), rotation_weight (7)}`
- Submap (field 10): `{layer (2) {submap_id (1), submap_2d (2) {local_pose (1), grid (4) {limits (1) {resolution (1), max (2), cell_limits (3)}, cells (2)}}}}`, three layers per submap.

**Cells** are packed int32s. 0 means unknown. Anything else is a correspondence cost, `0.1 + (v - 1) * 0.8 / 32766`, and wall probability is `1 - cost`. Cell (row, col) sits at `x = max.x - (row + 0.5) * r`, `y = max.y - (col + 0.5) * r` in the submap's local frame. Global position is `submap_pose * local_pose⁻¹ * local point`.

`server/map_preview.py` renders these files. The node chunks are small (about 68 bytes) and carry no point clouds.

## Map slots

`server/tools/map_slots.sh` keeps named maps in `/data/lucy_local/maps/<name>/`: the pbstream, the database rows, an info file and a timestamp.

```
python tools/lucy_sh.py tools/map_slots.sh MODE=list
python tools/lucy_sh.py tools/map_slots.sh MODE=save NAME=home
python tools/lucy_sh.py tools/map_slots.sh MODE=load NAME=home
```

`load` and `blank` first auto-save the current map as `_before_<time>`, then restart `cloud_node`.

## Zones and rooms

Keep-out and clean zones are sent live, with no restart: `LUCY_MAP_MGR` on rx key 18, carrying base64 of `MapManageDataItemMsg`. `path_type` is 0 keep-out, 1 designated area, 2 patrol route, 3 room segmentation, 4 semantic.

```
POST: {command POST(1), type PATH(2), map_paths{map_id, path_type,
       paths[Path2DMsg{path_id, path_name, pose[Affine2D theta=1,x=2,y=3], state=1}]}}
RUN:  {command RUN(3), field 2 = 200, type PATH_COMMAND(3),
       path_command{map_id, path_type 1 or 3, path_ids}}
```

A RUN starts by itself. Non-rectangular keep-outs work. Room names are stored in `data.db` by SQL `UPDATE`.

## Map guard

`server/map_guard.py` checks every 60 s.

- If a tracking run saves a map under 0.7x the guarded size, it waits until she's idle, then restores the guarded map. This caught a real case, where a short run saved a 47 KB map over an 846 KB one.
- It copies each new map 100 to a `_piece_<time>` slot, because she would otherwise delete it. This code is newer and hadn't yet been seen catching a real piece at the time of writing.
- It keeps tar backups of all the slots on the server.

## Map melding (in progress)

The goal is to drive her into a room that's normally shut, map only that, and add it to the main map.

`server/map_merge.py` can already do the file surgery. A map can hold several trajectories, so a merge:

1. renumbers the piece's trajectory,
2. moves its global poses into the main map's frame,
3. appends its submaps, nodes, constraints and options,
4. adds INTER_SUBMAP constraints to nearby main-map submaps, using her own weights (11000 / 100000).

```
python map_merge.py selftest <map.pbstream>
python map_merge.py info <map.pbstream>
python map_merge.py merge <main> <piece> <out> [--guess x,y,deg]
```

**Tested:**

- Round trip: all 186 chunks identical.
- Self-test: split a two-trajectory map, moved one part by 45 cm and 9°, and found it again to within one 5 cm cell.
- A rebuilt map loaded on the robot, and she relocalised on it in about 20 s.

**Not working yet:** placing a real piece. The test piece was a small hallway run with temporary clutter on the floor, and it overlapped the main map very little. Automatic wall matching gave no convincing fit, so nothing has been merged for real.

**Planned:**

- A manual fit page with the piece overlaid on the main map, nudge and turn buttons, and auto-fit only as a starting suggestion.
- An option to add only what's past the old map's edges. Piece cells the main map already knows get set to unknown, leaving a band about 25 cm wide so new walls can join up. Temporary clutter in the known area is then ignored.
- Merging into a new slot, never straight over the main map.
