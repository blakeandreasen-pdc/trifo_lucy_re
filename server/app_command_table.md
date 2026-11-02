# Trifo Home app (v2.6.3) command table

Decompiled from `Lucy Dump\Trifo Home_2.6.3_APKPure.apk` (class `r2.f`) on 2026-10-15 with
androguard (`tools\apk_find.py` / `tools\apk_class.py` / `tools\apk_cmdtable.py`).

Every command is a QLRQDataItem sent over the rx channel (opcode 0x0402) as
`{"head":"rq","key":K,"cmd":C,"data":D,...}`. **Lucy routes by `key`**, not by `cmd`.
Replies come back as QLRPDataItem ("rp"), possibly split (`index`/`sum`) and LZ4-compressed
(`lz4_source_size`).

Key families: 1 = device info, 2 = general commands, 3 = clean info/settings, 5 = tasks,
8 = map, 10 = streaming, 11 = status, 12 = go-to point, 13 = spiral, 14 = voice talk,
15 = system config, 16 = monitor, 17 = test bot, 18 = Lucy map/pose/map manager, 20 = log
records, 21 = do-not-disturb, 22 = custom clean (unsupported on this firmware: "app message error,22").

Verified on Lucy: A2B (12, "x,y" metres), SPIRAL via key 13 in manual mode, MANCTRL (2),
BLOWER via smart-speaker blowerMode. Not yet answered: GET_LUCY_POSE/GET_SIMPLE_MAP (18),
RTMP_PARAM/VOICETALK_PARAM (10), GET_SPOT_CLEANING_INFO (3) - accepted, no reply seen.

```
A      key=2    cmd=LANGUAGE                           args=(String p3) data=p3
B      key=2    cmd=VOICE                              args=(String p3) data=p3
C      key=2    cmd=VOICE_VOLUME                       args=(String p3) data=p3
E0     key=10   cmd=RTSP_THROB                         args=() data=
F      key=2    cmd=FEEDBACK_PROBLEM                   args=(com.trifo.trifohome.bean.FeedbackBean p4) data=com.trifo.trifohome.App.q().toJson(p4)
G      key=2    cmd=BLOWER                             args=(Object p3) data=p3.toString()
G0     key=2    cmd=APP_INFO                           args=(com.trifo.trifohome.event.AppInfo p4) data=com.trifo.trifohome.App.q().toJson(p4)
H0     key=10   cmd=STREAM_CONTROL                     args=(Object p3) data=v3_1
I      key=16   cmd=DELETE_MONITOR_RESULT              args=(String p3) data=p3
J0     key=17   cmd=SET_TEST_BOT                       args=(Object p3) data=p3.toString()
K0     key=2    cmd=CHARGER_BASE_CTRL                  args=(int p3) data=v1_3.toString()
L0     key=22   cmd=SET_CUSTOM_CLEAN_PARAM             args=(byte[] p3) data=android.util.Base64.encodeToString(p3, 2)
M      key=14   cmd=STOP_TALK                          args=(Object p3) data=p3.toString()
O0     key=15   cmd=SET_MAP_MANAGE_STATE               args=(String p3) data=p3
P      key=11   cmd=ALL_INFO_JSON                      args=() data=
Q      key=10   cmd=VOICETALK_PARAM                    args=() data=
S      key=17   cmd=GET_TEST_BOT                       args=() data=
S0     key=15   cmd=SET_MONITOR_STATE                  args=(String p3) data=p3
T      key=5    cmd=GET_CUSTOM_CLEAN_PLAN              args=() data=
T0     key=21   cmd=SET_DONOT_DISTURB_MODE             args=(String p3) data=p3
U      key=5    cmd=GET_TASK                           args=() data=
U0     key=15   cmd=SET_MONITOR_PERSON_ONLY_STATE      args=(Object p3) data=p3.toString()
V      key=3    cmd=CLEAN_TASKS_STATE                  args=() data=
W      key=22   cmd=GET_CUSTOM_CLEAN_PARAM             args=() data=
X      key=16   cmd=GET_MONITOR_DETAIL                 args=(Object p3) data=p3.toString()
X0     key=15   cmd=SET_USER_COUNTRY                   args=(String p3) data=p3
c      key=11   cmd=ALL_INFO                           args=() data=
c0     key=18   cmd=GET_LUCY_MAP                       args=(String p3) data=p3
d0     key=18   cmd=GET_LUCY_POSE                      args=() data=
e1     key=14   cmd=START_TALK                         args=(Object p3) data=p3.toString()
f      key=3    cmd=CLEAN_INFO                         args=() data=
g1     key=20   cmd=LOG_RECORD_CONTROL                 args=(String p3) data=p3
h0     key=8    cmd=GET_MAP                            args=() data=
h1     key=2    cmd=SPOT_CLEANING                      args=(String p3) data=p3
j0     key=16   cmd=GET_MONITOR_VIDEO                  args=(String p3) data=p3
j1     key=12   cmd=A2B                                args=(float p3, float p4) data=v1_3.toString()
k      key=1    cmd=FIRMWARE_VERSION                   args=() data=
k0     key=1    cmd=NET_INFO                           args=() data=
k1     key=12   cmd=A2B_NO_CLEAN                       args=(float p3, float p4) data=v1_3.toString()
l      key=2    cmd=FIND_ME                            args=() data=
l0     key=21   cmd=GET_DONOT_DISTURB_MODE             args=() data=
m0     key=10   cmd=RTMP_PARAM                         args=() data=
n      key=3    cmd=RESTART_CLEAN                      args=() data=
n0     key=20   cmd=LOG_RECORD_LIST                    args=() data=
o      key=3    cmd=LANGUAGE                           args=() data=
p      key=3    cmd=VOICE                              args=() data=
p0     key=18   cmd=GET_SIMPLE_MAP                     args=() data=
q      key=3    cmd=VOICE_VOLUME                       args=() data=
q0     key=3    cmd=GET_SPOT_CLEANING_INFO             args=() data=
r0     key=3    cmd=REPORT_STAIN_AREA                  args=() data=
s      key=2    cmd=BIND_STATE                         args=(Object p5) data=
s0     key=15   cmd=GET_SYSTEM_CONFIG                  args=() data=
t      key=2    cmd=BIND_STATE                         args=() data=
u0     key=10   cmd=RTMP_THROB                         args=() data=
v0     key=2    cmd=MANBLOWER                          args=(Object p3) data=p3.toString()
w0     key=2    cmd=MANCTRL                            args=(Object p3) data=p3.toString()
x      key=15   cmd=SET_IGNORE_VACUUM_BLOCK_MODE       args=(int p3) data=v1_3.toString()
x0     key=20   cmd=LOG_RECORD_FILE_OPERATION          args=(String p3) data=p3
y0     key=18   cmd=LUCY_MAP_MGR                       args=(byte[] p3) data=android.util.Base64.encodeToString(p3, 2)
z      key=2    cmd=RESTART_CLEAN                      args=(Object p3) data=p3.toString()
```
