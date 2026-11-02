"""Make Lucy say things: text -> neural voice (edge-tts) -> WAV -> played on her own speaker.

Plays straight on the robot with tinyplay (her codec is card 0, es8316; her own prompts are
16-bit 44.1 kHz stereo WAVs in /data/user/app/audio), so unlike tools/talk.py (the intercom)
it needs no manual mode or live stream and doesn't interrupt a run. The DAC switches are off
when she's quiet: turned on for the clip, then back off (2026-10-25).

    python say.py "Hello" [voice]"""
import asyncio
import os
import subprocess
import sys
import tempfile
import threading

import lucy_live

VOICES = ["en-GB-SoniaNeural", "en-GB-RyanNeural", "en-GB-LibbyNeural", "en-GB-MaisieNeural",
          "en-GB-ThomasNeural", "en-IE-EmilyNeural", "en-IE-ConnorNeural", "en-AU-NatashaNeural",
          "en-US-AriaNeural", "en-US-GuyNeural"]
REMOTE = "/data/lucy_local/say.wav"
PLAY = f"""tinymix 32 1 </dev/null; tinymix 34 1 </dev/null; tinymix 1 4 4 </dev/null
tinyplay {REMOTE} </dev/null >/dev/null 2>&1
tinymix 32 0 </dev/null; tinymix 34 0 </dev/null; tinymix 1 0 0 </dev/null
echo played
"""
# Her own prompts are squashed loud (about -10 LUFS, peaks at 0 dB); edge-tts comes out ~-17 LUFS,
# which sounded jarring next to them. Compress a little, then normalise to match (2026-10-26).
LOUD = "acompressor=threshold=-24dB:ratio=3:attack=5:release=120:makeup=2,loudnorm=I=-10:TP=-1:LRA=6"
_lock = threading.Lock()


def _wsl(p):
    p = os.path.abspath(p).replace("\\", "/")
    return "/mnt/" + p[0].lower() + p[2:]


def make_wav(text, voice, rate="+0%", pitch="+0Hz", gain_db=0):
    import edge_tts
    d = tempfile.mkdtemp(prefix="lucysay_")
    mp3, wav = os.path.join(d, "s.mp3"), os.path.join(d, "s.wav")
    asyncio.run(edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(mp3))
    subprocess.run(["wsl", "-e", "ffmpeg", "-y", "-loglevel", "error", "-i", _wsl(mp3),
                    "-af", f"volume={gain_db}dB," + LOUD, "-ar", "44100", "-ac", "2", "-sample_fmt", "s16",
                    _wsl(wav)], check=True, timeout=60)
    return wav


def play_file(wav):
    data = open(wav, "rb").read()
    cmd = ["ssh", "-i", lucy_live.SSH_KEY] + lucy_live.SSH_OPTS + [lucy_live.SSH_HOST, f"cat > {REMOTE}"]
    subprocess.run(cmd, input=data, capture_output=True, timeout=60, check=True)
    out = lucy_live.ssh_run(PLAY, timeout=120)
    return bool(out and b"played" in out)


def say(text, voice=VOICES[0], rate="+0%", pitch="+0Hz", gain_db=0):
    text = (text or "").strip()[:600]
    if not text:
        return {"ok": False, "out": "nothing to say"}
    if voice not in VOICES:
        voice = VOICES[0]
    with _lock:                    # one clip at a time
        try:
            wav = make_wav(text, voice, rate, pitch, gain_db)
            ok = play_file(wav)
        except Exception as e:
            return {"ok": False, "out": str(e)[:300]}
    return {"ok": ok, "out": "said it" if ok else "couldn't play it on her"}


if __name__ == "__main__":
    print(say(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else VOICES[0]))
