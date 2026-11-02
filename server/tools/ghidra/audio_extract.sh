#!/bin/sh
# audio_extract.sh <in.mp4> <out_base>  -> <out_base>.m4a (audio only) + <out_base>_spec.png (spectrogram)
ffmpeg -hide_banner -loglevel error -y -i "$1" -vn -c:a copy "$2.m4a"
ffmpeg -hide_banner -loglevel error -y -i "$1" -lavfi "showspectrumpic=s=1200x500:legend=1:scale=log" "$2_spec.png"
