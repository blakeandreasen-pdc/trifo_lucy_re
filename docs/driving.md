# Driving

The old app's manual control (`MANCTRL`) is a poor fit for smooth driving: each `ANGLE` command is a fixed motion of about 2.3 s that can't be cut short. So live driving talks directly to the robot's internal services.

## Internal sockets

Her processes talk over ZeroMQ (ZMTP 3.0, NULL mechanism) on unix sockets, `/data/local/tmp/TrifoIPC_<topic>_REQ` and `_REP`.

- `_REQ` is a ROUTER, so connect as DEALER and send commands.
- `_REP` is a PUB carrying replies.
- Each message is one frame: `RPCRequestBase {1 id, 2 type, 3 attribute, 4 priority (100), 7 timestamp, 8 ServiceMsg}`.

`sensor_node` owns the MCU serial port and serves:

- `planning_actor-motion_command`: wheels
- `txen_driver-robot_utility_command`: brushes, fan, lights, voice

`server/onrobot/zq.c` is a minimal ZeroMQ client that runs on the robot, and `server/drive_proto.py` builds the frames.

## Warning: use her boot clock

**Field 7 must be CLOCK_BOOTTIME in microseconds.** `sensor_node` refuses any OVERWRITE request older than the newest it has seen. One test with an epoch timestamp locked out her guidance, so she couldn't dock. It took a full reboot to clear. `zq @id:payloadhex` builds the wrapper on the robot with the correct clock, so use that.

## Motion commands

`ServiceMsg 4` is `MotionCommandItemMsg {1 move, 2 rotate, 3 wall_follow, 4 stop, 5 dock, 6 target_pose, 7 velocity, 8 motion_response}`.

- `move {direction 3, wheel_speed 4.0, distance 0.35}` is her own back-off from the dock.
- `velocity` is accepted and reaches the MCU, but the wheels ignore it.
- `move`, `rotate` and `target_pose` all work. Top speed is about 10 (roughly 0.25-0.3 m/s), and higher values are capped.

The live joystick (`server/drive_link.py`) keeps a single `zq ... DEALER -s` connection open, because new connections take 1-2 s to be heard. It smooths the input and has a 0.6 s dead-man stop.

## Suction and brushes in manual mode

The old app's manual screen sends `SET_TEST_BOT` on key 17 with BlowerParamBean JSON (blower, main brush, side brush). It works in manual mode. Manual mode alone turns the side brush on at 30.

## Parking view

`server/park_view.js` draws her map plus obstacles from the depth camera, for driving when the video isn't enough.

- `server/onrobot/depthscan.c` reads the ToF point cloud from shared memory, keeps points 2-11 cm above the floor (plus 2.5 cm per metre of distance), and sends about 5 frames per second.
- `depth_calib.json` holds the floor plane for this robot: camera 7.1 cm up, pitched up 6°. Recalibrate for your own.
- Bump tests put depth accuracy at a few centimetres.
- `server/align.py` can line the map up with the depth data. This only moves the view and never affects the robot.

Path prediction, echo arcs, beeps and camera badges were all tried and dropped, as they were jumpy and cost responsiveness on a phone.

Driving mode is at `/view?drive`.
