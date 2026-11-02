#!/bin/sh
# grep the jadx-decompiled Trifo app.   sh apk_grep.sh "<regex>" [subdir]
cd "/mnt/c/Claude/Lucy Dump/apk_jadx/sources" || exit 1
grep -rnE "$1" --include=*.java "${2:-.}" | cut -c1-220 | head -${3:-40}
