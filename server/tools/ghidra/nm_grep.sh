#!/bin/sh
# List defined dynamic symbols of an ARM64 ELF matching a regex.   sh nm_grep.sh <binary> "<regex>"
aarch64-linux-gnu-nm -D --defined-only "$1" | awk '{print $3}' | grep -i -E "$2" | sort
