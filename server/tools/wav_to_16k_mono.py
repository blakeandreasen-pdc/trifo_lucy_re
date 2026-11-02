"""Convert 16-bit PCM WAVs (any rate/channels) to 16 kHz mono for speech recognition.
Pure stdlib (audioop is gone in Python 3.13+), simple averaging resampler.

    python wav_to_16k_mono.py <in_dir> <out_dir>
"""
import array
import os
import sys
import wave

src, dst = sys.argv[1], sys.argv[2]
os.makedirs(dst, exist_ok=True)
for name in sorted(os.listdir(src)):
    if not name.lower().endswith(".wav"):
        continue
    with wave.open(os.path.join(src, name)) as w:
        ch, rate, n = w.getnchannels(), w.getframerate(), w.getnframes()
        pcm = array.array("h", w.readframes(n))
    mono = pcm if ch == 1 else array.array("h", ((pcm[i] + pcm[i + 1]) // 2 for i in range(0, len(pcm) - 1, ch)))
    step = rate / 16000
    out = array.array("h")
    pos = 0.0
    while int(pos + step) <= len(mono):
        a, b = int(pos), int(pos + step)
        out.append(sum(mono[a:b]) // max(1, b - a))
        pos += step
    with wave.open(os.path.join(dst, name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(out.tobytes())
print("converted to", dst)
