#!/bin/bash
set -eu

RES="${STS_GAME_RESOURCES:-$HOME/Library/Application Support/Steam/steamapps/common/SlayTheSpire/SlayTheSpire.app/Contents/Resources}"
MTS="${STS_MODTHESPIRE_JAR:-$HOME/Library/Application Support/Steam/steamapps/workshop/content/646570/1605060445/ModTheSpire.jar}"
OUT="$(cd "$(dirname "$0")" && pwd)/build"

rm -rf "$OUT"
mkdir -p "$OUT/classes"
javac -source 8 -target 8 -encoding UTF-8 \
  -cp "$RES/desktop-1.0.jar:$RES/mods/BaseMod.jar:$RES/mods/CommunicationMod.jar:$MTS" \
  -d "$OUT/classes" "$(dirname "$0")"/src/steamstateexport/*.java
cp "$(dirname "$0")/ModTheSpire.json" "$OUT/classes/"
jar cf "$OUT/SteamStateExport.jar" -C "$OUT/classes" .
if [ "${STS_INSTALL_MOD:-1}" = "1" ]; then
  cp "$OUT/SteamStateExport.jar" "$RES/mods/SteamStateExport.jar"
fi
