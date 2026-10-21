#!/usr/bin/env bash
# Rebuild media/macmouse.mp4 and media/macmouse.gif from stage.html.
#   1. On Linux in a live Hyprland session with macmouse loaded:
#        python3 media/src/record.py media/src/demo-data.json
#   2. Here (any OS): NODE_PATH=<dir with playwright-core> BROWSER_EXECUTABLE=<chrome> media/src/render.sh
# music.mp3 is an ElevenLabs-generated instrumental bed (no narration).
set -euo pipefail
cd "$(dirname "$0")"
WORK=${WORK:-$(mktemp -d)}
python3 -c "import json;d=json.load(open('demo-data.json'));open('demo-data.js','w').write('window.DEMO='+json.dumps(d,separators=(',',':'))+';\n')"
[ -d "$WORK/frames" ] || node capture.cjs "$WORK/frames" 60  # reuse frames when WORK already has them
DUR=$(python3 -c "import os;print(len(os.listdir('$WORK/frames'))/60)")
# X (Twitter): H.264 High, yuv420p, 1080p60, AAC 48 kHz stereo, faststart.
ffmpeg -v error -y -framerate 60 -i "$WORK/frames/%06d.png" -i music.mp3 \
    -filter_complex "[1:a]atrim=0:$DUR,afade=t=in:d=0.4,afade=t=out:st=$(python3 -c "print($DUR-1.6)"):d=1.6,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[a]" \
    -map 0:v -map "[a]" -c:v libx264 -profile:v high -preset slow -crf 16 -pix_fmt yuv420p \
    -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest -movflags +faststart ../macmouse.mp4
ffmpeg -v error -y -framerate 60 -i "$WORK/frames/%06d.png" \
    -vf "fps=25,scale=1080:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=256:stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle" \
    -loop 0 ../macmouse.gif
ls -la ../macmouse.mp4 ../macmouse.gif
