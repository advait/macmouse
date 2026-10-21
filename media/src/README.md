# Demo video sources

`../macmouse.mp4` (1920×1080, 60 fps, 20.3 s, for X) and `../macmouse.gif`
(1080 px, 25 fps) are rendered from these files. Nothing is illustrative:

- `motion.py`: the shared input, four minimum-jerk hand movements as 1600 CPI
  mouse reports at 1000 Hz.
- `record.py`: plays that input through a uinput virtual mouse in a live
  Hyprland session, once with stock libinput at Omarchy's default settings
  (sensitivity 0, adaptive) and once through macmouse. It records Hyprland's actual
  cursor positions, and computes the macOS reference path from Apple's recorded
  accelerator outputs (`tests/vectors/speed-10.csv.gz`, the Fast end of the slider). Result in
  `demo-data.json`: macmouse equals the macOS path at all 5,450 samples. Stock
  Omarchy deviates by up to 1,589 px.
- `stage.html`: a deterministic canvas renderer (`renderAt(t)`). The flick and
  sweep are slowed on screen and labelled with their speed.
- `capture.cjs`: renders every frame with headless Chrome (playwright-core).
- `render.sh`: encodes the MP4 (H.264 High, yuv420p, AAC 48 kHz, −16 LUFS
  target, faststart) and the GIF.
- `music.mp3`: instrumental bed generated with ElevenLabs Music from
  `music-prompt.txt`. No narration.
- `omarchy-tokyo-night-winding-road.jpg`: Omarchy's stock tokyo-night wallpaper.
