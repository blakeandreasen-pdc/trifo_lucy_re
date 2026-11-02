#!/bin/sh
# Decompile functions by name regex from an already-imported Ghidra project (see ghidra_decompile.sh).
#   sh ghidra_funcs.sh <binary> "<name regex>" <out.c>
set -e
NAME=$(basename "$1")
PROJ=/tmp/ghidra_projects
if [ ! -d "$PROJ/$NAME.rep" ]; then
  mkdir -p "$PROJ"
  /opt/tools/ghidra/support/analyzeHeadless "$PROJ" "$NAME" -import "$1" -overwrite > /tmp/ghidra_import_$NAME.log 2>&1
fi
/opt/tools/ghidra/support/analyzeHeadless "$PROJ" "$NAME" -process "$NAME" -noanalysis \
  -scriptPath /mnt/c/Claude/wsl_toolbox/ghidra_scripts -postScript ${SCRIPT:-DecompileFunctions.java} "$2" "$3" > /tmp/ghidra_f_$NAME.log 2>&1
grep -E "decompiled|ERROR.*Script|Exception" /tmp/ghidra_f_$NAME.log | tail -3
