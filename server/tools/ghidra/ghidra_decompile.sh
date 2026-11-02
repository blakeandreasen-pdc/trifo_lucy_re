#!/bin/sh
# Import a binary into a cached Ghidra project (analysed once) and decompile the functions that
# reference strings matching a regex.
#   sh ghidra_decompile.sh <binary> "<regex>" <out.c>
set -e
BIN="$1"; RE="$2"; OUT="$3"
NAME=$(basename "$BIN")
PROJ=/tmp/ghidra_projects
mkdir -p "$PROJ"
SCRIPTS=/mnt/c/Claude/wsl_toolbox/ghidra_scripts
if [ ! -d "$PROJ/$NAME.rep" ]; then
  /opt/tools/ghidra/support/analyzeHeadless "$PROJ" "$NAME" -import "$BIN" -overwrite \
    -scriptPath "$SCRIPTS" -postScript DecompileStringRefs.java "$RE" "$OUT" > /tmp/ghidra_$NAME.log 2>&1
else
  /opt/tools/ghidra/support/analyzeHeadless "$PROJ" "$NAME" -process "$NAME" -noanalysis \
    -scriptPath "$SCRIPTS" -postScript DecompileStringRefs.java "$RE" "$OUT" > /tmp/ghidra_$NAME.log 2>&1
fi
grep -E "decompiled|ERROR|Exception" /tmp/ghidra_$NAME.log | tail -5
