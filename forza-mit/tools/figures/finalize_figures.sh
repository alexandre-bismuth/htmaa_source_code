#!/bin/sh
# Turn a run_figures_tour.sh output folder into docs/figures media.
# usage: finalize_figures.sh <tour outdir>
#   stills: PNG -> JPG q90 (2560x1440); clip: frames -> H.264 yuv420p + AAC, faststart.
# CLIP_START / CLIP_LEN (seconds into the 60 fps sequence) trim the clip; CLIP_FPS = output fps (60).
set -e
IN=$1
DST="$(cd "$(dirname "$0")/../.." && pwd)/docs/figures"
mkdir -p "$DST"
jpg() { magick "$IN/$1.png" -quality 90 "$DST/$2.jpg"; echo "$2.jpg $(du -h "$DST/$2.jpg" | cut -f1)"; }
jpg car_front34_killian        01_car_front_three_quarter
jpg chase_media_lab            02_chase_cam_mit_media_lab
jpg aerial_mit_core            04_aerial_mit_core_landmarks
jpg chase_mass_ave             05_chase_cam_mass_ave
jpg car_rear34_bridge          06_car_rear_harvard_bridge_skyline
jpg killian_high               07_killian_court_great_dome
jpg chase_dash_midrace         08_race_checkpoint_hud
jpg chase_results              09_race_results
jpg chase_full_map             10_full_map_landmarks

SEQ=$IN/chase_clip_timed_lap
START=${CLIP_START:-0.5}; LEN=${CLIP_LEN:-30}; FPS=${CLIP_FPS:-60}
AUDIO=$IN/chase_clip_timed_lap.wav
set -- -framerate 60 -start_number 0 -i "$SEQ/f%04d.png"
[ -f "$AUDIO" ] && set -- "$@" -i "$AUDIO"
MAPA=""; [ -f "$AUDIO" ] && MAPA="-map 1:a -c:a aac -b:a 160k"
ffmpeg -y -loglevel error "$@" -ss "$START" -t "$LEN" -map 0:v $MAPA \
  -vf "scale=1920:1080:flags=lanczos,fps=$FPS" -shortest -c:v libx264 -preset slow -crf ${CLIP_CRF:-22} -maxrate 6800k -bufsize 13600k \
  -pix_fmt yuv420p -movflags +faststart "$DST/03_timed_lap_start.mp4"
ffprobe -v error -show_entries format=duration,size -of compact "$DST/03_timed_lap_start.mp4"
# review montage: 12 frames evenly over the clip (3 x 4), each stamped with its time
M=${MONTAGE:-$(dirname "$IN")/clip_montage.jpg}
FONT="/System/Library/Fonts/Supplemental/Arial Bold.ttf"
T=$(mktemp -d)
for k in 0 1 2 3 4 5 6 7 8 9 10 11; do
  t=$(python3 -c "print(round(($k + 0.5) * $LEN / 12, 2))")
  ffmpeg -y -loglevel error -ss "$t" -i "$DST/03_timed_lap_start.mp4" -frames:v 1 -vf scale=640:-1 "$T/m$k.png"
  magick "$T/m$k.png" -font "$FONT" -pointsize 26 -fill white -undercolor '#000000a0' -annotate +10+32 " ${t} s " "$T/m$k.png"
done
magick \( "$T/m0.png" "$T/m1.png" "$T/m2.png" +append \) \( "$T/m3.png" "$T/m4.png" "$T/m5.png" +append \) \
       \( "$T/m6.png" "$T/m7.png" "$T/m8.png" +append \) \( "$T/m9.png" "$T/m10.png" "$T/m11.png" +append \) -append -quality 88 "$M"
rm -rf "$T"; echo "montage $M"
