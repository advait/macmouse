# How macOS moves the mouse pointer

This describes what macOS 26.5 (build 25F71, Apple silicon) does with a USB mouse's
movement reports, as determined for this project and verified bit for bit against
the installed system code. It covers ordinary relative mice that use the default
acceleration table, which is the common case for third-party mice.

## The pipeline at a glance

```
HID report (dx, dy integer counts)
  │  1. IOHIDPointerScrollFilter: table acceleration, per report      (binary64)
  ▼
accelerated vector (dx', dy')
  │  2. NX event translation: deltas stored as IEEE binary32           (float)
  ▼
NX motion deltas (nx, ny)      ── if both are exactly 0, no cursor motion
  │  3. WindowServer: add to the cursor position, clip to displays,
  │     store the position as signed 24.8 fixed point (truncating)
  ▼
cursor position in points (1/256-point lattice)
```

Everything happens **per HID report**. With this configuration there is no
dependence on time between reports, no smoothing and no averaging. A mouse polling
at 1000 Hz gets 1000 independent applications of the curve per second.

## 1. Table acceleration

### Inputs

- `dx, dy`: the raw signed counts from one report. macOS does not normalize them
  by the mouse's actual DPI. The accelerator is built with a nominal *resolution* of
  400 counts/inch (`HIDPointerResolution`, the default for mice that do not declare
  one). A 1600 CPI mouse therefore moves the pointer four times as far per inch as a
  400 CPI mouse. **Set your mouse to the same CPI on both machines.**
- The *tracking speed* slider (`defaults read -g com.apple.mouse.scaling`). It
  selects which curve is interpolated out of Apple's default acceleration table. See
  [Tracking speed](#tracking-speed) for its ten positions.
- Report-rate scaling (`HIDPointerReportRate`/accelerator rate) is **0** for these
  mice, which disables every timestamp-dependent branch.

### The curve

Apple stores pointer acceleration as a compact table of curves, one per
tracking-speed value, published in Apple's open-source IOHIDFamily as
`defaultAccelTable`. When the mouse service starts, macOS interpolates the curve for
the current tracking speed and resolution and converts it into a list of linear
segments `(m, b, x)`. This repository stores the segments macOS builds for each
slider position at resolution 400, read losslessly as binary64 from the running
system's own constructor (`profiles/tracking-speeds.hex.csv`). At the Fast end
(tick 10, scaling 3) there are nine:

| segment | applies while magnitude ≤ | m (slope) | b (intercept) |
| --- | --- | --- | --- |
| 1 | 2.6406 | 0.406958 | 0 |
| 2 | 25.7176 | 2.002387 | −4.212948 |
| 3 | 71.6418 | 4.898401 | −78.691397 |
| 4 | 136.8542 | 1.933521 | 133.717934 |
| 5 | 174.5121 | 0.722927 | 299.392795 |
| 6 | 205.7405 | 0.137647 | 401.531115 |
| 7–9 | (and beyond) | 0 | 429.850746 |

> Don't rebuild these from `hidutil` output. Its serialization rounds the
> coefficients to unsigned 16.16 fixed point, which erases the two negative
> intercepts (−4.21 and −78.69) and visibly changes the curve.

### Tracking speed

System Settings' slider snaps to ten positions, and each writes one value to
`com.apple.mouse.scaling`. The values come from the Mouse settings extension:

| tick | 1 (Slow) | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 (Fast) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| scaling | 0 | 0.125 | 0.5 | 0.6875 | 0.875 | 1 | 1.5 | 2 | 2.5 | 3 |
| segments | 1 | 10 | 10 | 10 | 10 | 9 | 9 | 9 | 9 | 9 |

The scaling value goes to the mouse's event filter unchanged as
`HIDMouseAcceleration` (16.16 fixed point), and the filter builds the table curve for
it. Only the curve changes between ticks; the per-report arithmetic below, rate 0
and resolution 400 stay the same. Output in points per report:

| counts per report | 1 | 4 | 10 | 20 | 40 | 100 | 250 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| tick 1 | 0.240 | 0.960 | 2.400 | 4.800 | 9.600 | 24.0 | 60.0 |
| tick 2 | 0.208 | 1.034 | 3.088 | 6.440 | 15.73 | 41.4 | 79.4 |
| tick 3 | 0.222 | 1.429 | 5.153 | 11.36 | 34.11 | 93.8 | 137.5 |
| tick 4 | 0.229 | 1.626 | 6.185 | 13.82 | 43.30 | 119.9 | 166.5 |
| tick 5 | 0.235 | 1.824 | 7.217 | 16.28 | 52.50 | 146.1 | 195.6 |
| tick 6 | 0.203 | 1.898 | 7.905 | 17.92 | 58.62 | 163.5 | 214.9 (cap) |
| tick 7 | 0.254 | 2.373 | 9.882 | 22.40 | 73.28 | 204.4 | 268.7 (cap) |
| tick 8 | 0.305 | 2.847 | 11.86 | 26.88 | 87.93 | 245.3 | 322.4 (cap) |
| tick 9 | 0.356 | 3.322 | 13.84 | 31.36 | 102.6 | 286.2 | 376.1 (cap) |
| tick 10 | 0.407 | 3.797 | 15.81 | 35.83 | 117.2 | 327.1 | 429.9 (cap) |

Tick 1 has no acceleration at all: one linear segment, 0.24 points per count. Ticks 2–5
accelerate, then keep growing slowly. Ticks 6–10 share one shape scaled up, and
level off at a per-report cap.

### Per-report arithmetic

```
magnitude = floor(sqrt(dx*dx + dy*dy))       # no fused multiply-add here
v         = max(magnitude, 2^-16)
segment   = first segment with v <= x, else the last segment
gain      = fma(m, v, b) / v                 # Apple's binary uses FMADD here
dx', dy'  = dx * gain, dy * gain
```

Things that matter for exactness:

- The **magnitude is floored** before the lookup, but the gain multiplies the
  original components, so direction is preserved exactly. `(1,1)` and `(1,0)` both
  look up magnitude 1.
- `m*v + b` is a single **fused** multiply-add in the shipped ARM64e code; every
  other operation is an ordinary IEEE binary64 operation. The portable model
  (`src/pointer_profile.hpp`) calls `std::fma` explicitly and is compiled with
  `-ffp-contract=off -fno-fast-math` so the compiler adds no other fusion.
- The output is a vector of doubles; nothing is rounded at this stage.

### What the curve feels like

Output per report on a 1600 CPI mouse at 1000 Hz (`n` counts in one report means
moving at about `0.625·n` inches/second):

| counts per report | output (points) | gain |
| --- | --- | --- |
| 1 | 0.407 | 0.41 |
| 2 | 0.814 | 0.41 |
| 3 | 1.794 | 0.60 |
| 4 | 3.797 | 0.95 |
| 6 | 7.801 | 1.30 |
| 10 | 15.811 | 1.58 |
| 20 | 35.835 | 1.79 |
| 40 | 117.245 | 2.93 |
| 60 | 215.213 | 3.59 |
| 80 | 288.400 | 3.61 |
| 100 | 327.070 | 3.27 |
| ≥ 217 | 429.851 (cap) | falls off |

Slow, precise movement is heavily damped: about 0.41 points per count, so roughly
2.5 counts per point. Gain rises steeply between about 3 and 70 counts per
millisecond. Above about 217 counts per report, output is capped at 429.85 points
per report.

Compare libinput's default "adaptive" profile on Linux. It estimates *velocity*
from a history of events and timestamps, normalizes to 1000 DPI, and applies a
smooth curve scaled by `sensitivity`. The two differ in shape, in units, and in being
stateless versus history-based, so no libinput setting reproduces macOS.

## 2. NX translation: binary32

The accelerated doubles are packed into the legacy NX mouse-moved event, which
stores the deltas as IEEE **binary32**: round-to-nearest-even conversion of each
component. If *both* converted components are exactly zero, no motion event is
generated. The cursor does not move and no zero-length motion is delivered.

## 3. WindowServer: 24.8 fixed-point cursor position

WindowServer adds the binary32 deltas (widened back to double) to the current
cursor position in global display points. It clips to the display arrangement and
stores the result as **signed 24.8 fixed point**, converting with *truncation
toward zero*:

```
p_next = trunc(256 * (p + n)) / 256        # per axis
```

So the cursor lives on a 1/256-point lattice, and sub-lattice remainders are
discarded rather than carried. In positive coordinates this loses up to 1/256 point
per event moving right or down, and gains nothing moving left or up. The asymmetry
is tiny but real.

## Physical scale

macOS cursor coordinates are **points**, not device pixels. On a Retina or HiDPI
display one point is 2×2 pixels. The same hand movement produces the same number
of points on any Mac display, so its physical distance depends on the display's
millimetres per point. Hyprland's logical pixels play the same role: physical pixels
divided by the monitor `scale`. To feel identical, match **mm per point** on the Mac
with **mm per logical pixel** on Linux, using `physical width / logical width`:

| display | logical width | width (mm) | mm per unit |
| --- | --- | --- | --- |
| 32" 6K at "looks like 3008×1692" (macOS) | 3008 | 701 | 0.233 |
| 27" 4K at Hyprland scale 1.5 | 2560 | 590–600 | 0.230–0.234 |

## How macmouse reproduces this on Linux

`src/macmouse.cpp` is a Hyprland plugin. For mice listed in
`~/.config/macmouse/devices`, it hooks `CInputManager::onMouseMoved`. It takes
libinput's *unaccelerated* counts, which are exactly the per-report integer counts
since the kernel emits one evdev frame per HID report, and computes steps 1–2. It
then hooks `CPointerManager::move` to apply step 3 against the cursor position at
move time. It hands Hyprland the step `p_next − p`, which binary64 addition maps
exactly onto the lattice point. libinput's own acceleration and `sensitivity` are
ignored for those mice. Raw relative-pointer data (games) is unchanged, and other
devices keep stock behavior.

What is not reproduced: screen-edge clipping follows each OS's own monitor
layout, sensor differences between physical mice, and display latency.

## Scope and honesty

- Verified: steps 1–3 as arithmetic, against Apple's own code (see
  [VERIFICATION.md](VERIFICATION.md)), and their execution inside Hyprland's real
  input path.
- Assumed: macOS forwards each motion event immediately for third-party mice
  rather than resampling it. Static analysis of WindowServer's drag-interpolation
  predicate supports this, but it was not observed live. If it were wrong, it would
  affect timing, not distance.
- macOS 26.5, default table, resolution 400, at the slider's ten positions. Values
  written outside the slider with `defaults write` would need their own segments.
- At every tick the live mouse filter on the reference Mac built a table accelerator
  with rate 0, resolution 400 and the same segments as the constructor this
  repository reads, so the per-report path above applies at all ten.
