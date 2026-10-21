# Verification

Everything here runs unattended: no physical mouse movement, no root.

## 1. Model vs Apple (`make check`)

`tests/vectors/speed-NN.csv.gz` holds 86,430 input/output pairs for each of the ten
tracking-speed ticks (864,300 in total). They were recorded by calling the
**installed** macOS 26.5 (25F71) ARM64e pointer accelerator in-process with
synthetic deltas, constructed for that tick's `com.apple.mouse.scaling` value. Inputs cover a dense grid of small integer deltas (−128…127
on both axes), large values across the 16-bit report range, signed zeros, and
subnormal and fractional values. The table also carries
synthetic timestamps; they are irrelevant at rate 0. `tests/check_model.cpp` runs
the portable model with each tick's segments on every input and requires
bit-identical binary64 outputs:

```
tick  1 (scaling 0): 86430 rows, 0 mismatches
...
tick 10 (scaling 3): 86430 rows, 0 mismatches
864300 rows, 0 mismatches
```

This passes with clang on Apple silicon and GCC on x86-64 Linux.

### Tracking-speed values and the live filter

The ten slider values (`0, 0.125, 0.5, 0.6875, 0.875, 1, 1.5, 2, 2.5, 3`) are the
values the macOS Mouse settings extension writes. To confirm the live system uses
the same curves, each value was set system-wide as `HIDMouseAcceleration` on the
reference Mac, and the mouse filter's own debug state was read with
`hidutil dump services`, then restored to 3. At every tick the filter held a table
accelerator with rate 0 and resolution 400, with the same segment count as the
stored profile. All 258 serialized coefficients equal the stored binary64 segments
after the filter's 16.16 serialization, which writes negative intercepts as 0.

## 2. Built-in self-test

At load time the plugin evaluates five of Apple's recorded vectors at each of the
ten ticks and compares the bits. If any differs, for example from a compiler or flag change, it never
transforms anything and shows a notification.

## 3. Nested compositor gate (`make nested`)

`tools/nested_check.py` starts a **new nested Hyprland**: its own config, no seat,
terminated afterwards. It loads the plugin and a test probe, which emits motion
events through Aquamarine/CMouse signals so they traverse the real hooked
`CInputManager::onMouseMoved` and `CPointerManager::move`. 3,000 inputs drawn from
Apple's fixture are replayed twice, with `input:force_no_accel` off and on, plus
600 events at each of the other nine tracking-speed ticks, against that tick's Apple
outputs. It also checks that `hyprctl macmouse speed` rejects anything but 1–10, and
replays 200 events from an unselected device. For every event it checks:

- table output equals **Apple's recorded output** (from the fixture, not the model)
- binary32 projection, recomputed independently in Python
- applied step and resulting cursor position equal the truncating 24.8
  recurrence, computed in Python from the start point
- unselected devices: cursor moves by exactly the stock libinput delta

`tools/load.sh` runs this gate whenever the Hyprland ABI or this repository's
build/verification inputs change, and only loads the exact ELF that passed.

## 4. Live session (`make verify`)

`tools/live_verify.py` creates a **uinput virtual mouse**. It needs write access
to `/dev/uinput`, which desktop distributions usually grant through a uaccess ACL;
no root is required. Events take the full real path: kernel → libinput → Aquamarine
→ hooked Hyprland, in your running session. It:

1. requires that your configured mouse is connected and selected
2. wakes DPMS first, because a modeset stalls the compositor and overflows
   evdev (SYN_DROPPED)
3. replays the same Apple-fixture inputs under `force_no_accel` off and on at
   tick 10, then 300 events at each other tick. Every event is checked as above,
   including that all-zero frames move nothing
4. checks that an unselected device keeps stock libinput acceleration
5. restores the cursor position, the option, the tracking speed and the device
   selection

The cursor visibly moves for about 10 seconds. Results on the reference machine
(Hyprland 0.56.2, Omarchy, three 4K monitors at scale 1.5):

| run | events | result |
| --- | --- | --- |
| live, force_no_accel off / on | 2,992 / 2,992 | exact |
| live, ticks 1–9 | 298–300 each | exact |
| soak (`--events 30000`), ~32 s each at 1 kHz | 29,879 / 29,879 | exact, 0 SYN_DROPPED |
| unselected device | 300 | stock values unchanged |

A deliberately broken earlier build failed the `force_no_accel` phase, so these
checks catch real mistakes.

## Not verified by software

Sensor accuracy differences between two physical mice, display size differences,
presentation latency, and live observation of macOS's delivery route (see
[ALGORITHM.md](ALGORITHM.md#scope-and-honesty)).
