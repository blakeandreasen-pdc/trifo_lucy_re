"""Frames for Lucy's internal motion/utility RPC sockets (sensor_node serves them):
    /data/local/tmp/TrifoIPC_planning_actor-motion_command_REQ   (guidance -> wheels)
    /data/local/tmp/TrifoIPC_txen_driver-robot_utility_command_REQ (brushes, fan, lights...)
Wire format (seen with strace, 2026-10-22): ZeroMQ (ZMTP 3.0) over unix sockets; _REQ is a ROUTER
(connect as DEALER, onrobot/zq), _REP is a PUB. Each message is one frame: RPCRequestBase
{1 id, 2 type ACT/CANCEL, 3 attribute OVERWRITE/APPEND/REPLY_ACK, 4 priority (100), 7 timestamp,
 8 payload ServiceMsg}. Replies come back on the _REP socket as RPCReplyBase {1 req_id,
 2 attribute, 3 timestamp, 4 payload} and the client acks them with {1 id, 3 REPLY_ACK, 4 100, 7 ts}.
ServiceMsg 4 = MotionCommandItemMsg {1 move, 2 rotate, 3 wall_follow, 4 stop, 5 dock, 6 target_pose,
 7 velocity {1 left f32, 2 right f32, 3 maintain_time ms, 4 command_id}, 8 motion_response}.
ServiceMsg 5 = RobotUtilityCommandItemMsg {1 repeated RobotUtilityCommandMsg {1 type, 99 id,
 3 motor_msg {1 motor_id, 2 duty_cycle}, ...}}.
Guidance's own back-off off the dock: move {direction 3, wheel_speed 4.0, distance 0.35}."""
import struct
import time

from lucy_proto import pb_bytes, pb_varint


def pb_f32(field, v):
    return bytes([(field << 3) | 5]) + struct.pack("<f", v)


def frame(req_id, payload, attribute=0, priority=100):
    """DON'T send these from the Surface: the timestamp must be her boot clock (zq @id:payload
    does that on the robot). Kept for reference/decoding."""
    body = (pb_varint(1, req_id) + (pb_varint(3, attribute) if attribute else b"")
            + pb_varint(4, priority) + pb_varint(7, int(time.time() * 1e6)) + pb_bytes(8, payload))
    return body          # one ZeroMQ frame (the "2-byte length" in strace was the ZMTP header)


def velocity(left, right, ms, cmd_id):
    v = pb_f32(1, left) + pb_f32(2, right) + pb_varint(3, int(ms)) + pb_varint(4, cmd_id)
    return pb_bytes(4, pb_bytes(7, v))


def stop(cmd_id):
    return pb_bytes(4, pb_bytes(4, pb_varint(1, cmd_id)))


def move(direction, speed, distance, cmd_id):
    m = pb_varint(1, direction) + pb_f32(2, speed) + pb_f32(3, distance) + pb_varint(5, 1) + pb_varint(6, cmd_id)
    return pb_bytes(4, pb_bytes(1, m))


def rotate(left, right, target, cmd_id, heading_type=1):
    """Guidance spins with left=-right (6-8) to an absolute heading (rad); arcs with e.g. 0.8/8 and
    target 6.2832; manual ANGLE:n uses target 1000 (= no target, keep going)."""
    r = pb_varint(1, heading_type) + pb_f32(2, left) + pb_f32(3, right) + pb_f32(4, target) + pb_varint(5, cmd_id)
    return pb_bytes(4, pb_bytes(2, r))


def target_pose(speed, x, y, cmd_id):
    """Seen during cleaning: {1 speed 7.0, 2 x, 3 y, 4 id}; x/y look robot-relative (m)."""
    t = pb_f32(1, speed) + pb_f32(2, x) + pb_f32(3, y) + pb_varint(4, cmd_id)
    return pb_bytes(4, pb_bytes(6, t))


def motor(utype, motor_id, duty, cmd_id):
    u = pb_varint(1, utype) + pb_bytes(3, pb_varint(1, motor_id) + pb_varint(2, duty)) + pb_varint(99, cmd_id)
    return pb_bytes(5, pb_bytes(1, u))


def hexframe(req_id, payload, **kw):
    return frame(req_id, payload, **kw).hex()
