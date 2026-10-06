#!/bin/sh
# Boston 3D buildings for the skyline backdrop (City of Boston Planning Department "3D Smart Model",
# tiled OBJ, same MA State Plane grid/offset as the Cambridge models). Usage: tools/mapgen/fetch_boston.sh
# -> data/raw/bos3d/<tile>/{catalog.csv, models/<Model_ID>_OBJ/*.obj}
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
RAW="$HERE/../../data/raw/bos3d"
URL=$(python3 -c "import json;print(json.load(open('$HERE/config.json'))['boston']['url'])")
# union of config boston.tiles and every region's boston_tiles
for TILE in $(python3 -c "import json;c=json.load(open('$HERE/config.json'));print(' '.join(sorted(set(c['boston']['tiles']).union(*[r.get('boston_tiles',[]) for r in c['regions'].values()]))))"); do
  DIR="$RAW/$TILE"
  if [ -f "$DIR/catalog.csv" ] && [ -d "$DIR/models" ]; then echo "$TILE: cached"; continue; fi
  mkdir -p "$DIR"
  curl -sfL "$(echo "$URL" | sed "s/{tile}/$(echo $TILE | tr - _)/")" -o "$DIR/tile.zip"   # files are named BOS_G_4_...
  (cd "$DIR" && unzip -q -o tile.zip && rm tile.zip)
  # one zip per building in objz/ -> models/<Model_ID>_OBJ/
  mkdir -p "$DIR/models"
  for Z in "$DIR"/objz/*.zip; do
    N=$(basename "$Z" .zip)
    mkdir -p "$DIR/models/$N" && unzip -q -o "$Z" -d "$DIR/models/$N"
  done
  rm -rf "$DIR/objz"
  echo "$TILE: $(ls "$DIR/models" | wc -l | tr -d ' ') models"
done
