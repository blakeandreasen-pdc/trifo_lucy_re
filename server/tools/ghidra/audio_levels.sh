#!/bin/sh
# Per-5s audio levels (RMS/peak dB) of a media file: audio_levels.sh <file>
f="$1"
ffprobe -v error -show_entries stream=index,codec_type,codec_name,sample_rate,channels -of compact "$f"
ffmpeg -hide_banner -nostats -i "$f" -vn -af "asetnsamples=n=220500,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-" -f null - 2>/dev/null | grep -o 'RMS_level=.*' | head -20
ffmpeg -hide_banner -nostats -i "$f" -vn -af volumedetect -f null - 2>&1 | grep -E 'mean_volume|max_volume'
