#!/usr/bin/env python3
"""Verify the loaded macmouse plugin in the live Hyprland session, unattended.

A uinput virtual mouse (user ACL on /dev/uinput, no privileges) sends Apple
fixture count sequences through the real kernel -> libinput -> Aquamarine ->
hooked CInputManager path. The plugin's trace is compared with Apple's recorded
accelerator outputs plus independent binary32/24.8 recurrence. A second phase
checks that an unselected device keeps stock libinput behavior. The cursor is
restored afterwards; no buttons or wheel are pressed. No physical device is used.
"""
import argparse
import fcntl
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import expect as mx  # noqa: E402

UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT = 0x40045564, 0x40045565, 0x40045566
UI_DEV_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY = 0x405C5503, 0x5501, 0x5502
EV_SYN, EV_KEY, EV_REL = 0, 1, 2
REL_X, REL_Y, REL_WHEEL = 0, 1, 8
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
NAME = 'Macmouse Virtual Test Mouse'
HL_NAME = 'macmouse-virtual-test-mouse'


class VirtualMouse:
    def __init__(self, name, vendor=0x1532, product=0x0085):
        self.fd = os.open('/dev/uinput', os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_REL)
        for b in (BTN_LEFT, BTN_RIGHT, BTN_MIDDLE):
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, b)
        for r in (REL_X, REL_Y, REL_WHEEL):
            fcntl.ioctl(self.fd, UI_SET_RELBIT, r)
        setup = struct.pack('<HHHH80sI', 0x03, vendor, product, 1, name.encode(), 0)
        fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)

    def emit(self, events):
        os.write(self.fd, b''.join(struct.pack('<qqHHi', 0, 0, t, c, v) for t, c, v in events))

    def move(self, dx, dy):
        events = []
        if dx:
            events.append((EV_REL, REL_X, dx))
        if dy:
            events.append((EV_REL, REL_Y, dy))
        events.append((EV_SYN, 0, 0))
        self.emit(events)

    def close(self):
        fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        os.close(self.fd)


def ctl(*args):
    return subprocess.run(['hyprctl', *args], capture_output=True, text=True, check=True).stdout.strip()


def mm(*args):
    return ctl('macmouse', *args)


def pos():
    x, y = mm('pos').split()
    return float.fromhex(x), float.fromhex(y)


def get_force():
    return ctl('getoption', 'input:force_no_accel').splitlines()[0].split()[-1] in ('true', '1')


def configured_devices():
    path = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'macmouse/devices'
    if not path.exists():
        return []
    return [d.strip() for line in path.read_text().splitlines() for d in line.split(',') if d.strip() and not d.startswith('#')]


def set_force(value):
    # Lua-config Hyprland (0.55+) uses eval; hyprlang configs accept keyword.
    out = subprocess.run(['hyprctl', 'eval', f'hl.config({{input={{force_no_accel={str(value).lower()}}}}})'],
                         capture_output=True, text=True).stdout.strip()
    if out != 'ok':
        out = ctl('keyword', 'input:force_no_accel', '1' if value else '0')
    if out != 'ok' or get_force() != value:
        raise RuntimeError(f'cannot set input:force_no_accel={value}: {out!r}')


def wait_device(present=True):
    for _ in range(100):
        names = [m['name'] for m in json.loads(ctl('-j', 'devices'))['mice']]
        if (HL_NAME in names) == present:
            return names
        time.sleep(0.05)
    raise RuntimeError(f'virtual mouse presence did not become {present}')


def send(mouse, inputs, interval):
    for dx, dy in inputs:
        mouse.move(dx, dy)
        time.sleep(interval)
    time.sleep(0.3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--events', type=int, default=3000)
    parser.add_argument('--interval-ms', type=float, default=1.0)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--speed-events', type=int, default=300, help='events per other tracking-speed tick')
    parser.add_argument('--out', default=None, help='result JSON path')
    parser.add_argument('--physical', default=None, help='configured mouse that must be connected and selected (default: first in ~/.config/macmouse/devices)')
    args = parser.parse_args()

    if 'macmouse' not in ctl('plugin', 'list'):
        raise SystemExit('macmouse plugin is not loaded in this session')
    original_status = json.loads(mm('status'))
    if not original_status['selftest']:
        raise SystemExit('plugin self-test failed')
    vectors = mx.apple_vectors()
    if original_status.get('speed') is None:
        raise SystemExit('loaded macmouse predates tracking-speed support; reload it (tools/load.sh)')
    # The synthetic device is added to the selection below; independently require
    # that the real mouse is connected and selected by the deployed configuration.
    if args.physical is None:
        args.physical = next(iter(configured_devices()), None)
    if args.physical is None:
        raise SystemExit('no device configured in ~/.config/macmouse/devices')
    if args.physical not in [m['name'] for m in json.loads(ctl('-j', 'devices'))['mice']]:
        raise SystemExit(f'physical mouse {args.physical} is not connected')
    if args.physical not in original_status['devices']:
        raise SystemExit(f'physical mouse {args.physical} is not selected by macmouse')
    force_original = get_force()
    monitors = json.loads(ctl('-j', 'monitors'))
    # Use the first unrotated monitor; logical box shrunk away from edges.
    mon = next(m for m in monitors if m['transform'] == 0)
    w, h = mon['width'] / mon['scale'], mon['height'] / mon['scale']
    box = (mon['x'] + 60, mon['y'] + 60, mon['x'] + w - 60, mon['y'] + h - 60)
    start = (float(int(mon['x'] + w / 2)), float(int(mon['y'] + h / 2)))

    inputs = mx.plan(vectors, args.events, start, box, seed=args.seed)
    inputs[5:5] = [(0, 0)] * 3  # all-zero frames: libinput emits nothing, Mac emits no motion
    work = Path(tempfile.mkdtemp(prefix='macmouse-live-'))
    saved = pos()
    mouse = VirtualMouse(NAME)
    result = {'passed': False}
    try:
        wait_device(True)
        time.sleep(1.0)
        # With monitors in DPMS off, the first motion wakes them and the modeset
        # stalls Hyprland's loop ~0.8 s; frames sent meanwhile are SYN_DROPPED.
        # Wake first (net-zero wiggle, before tracing), then wait for all outputs.
        for _ in range(10):
            mouse.move(1, 0); time.sleep(0.01); mouse.move(-1, 0); time.sleep(0.01)
        for _ in range(100):
            if all(m['dpmsStatus'] for m in json.loads(ctl('-j', 'monitors'))):
                break
            time.sleep(0.05)
        time.sleep(1.5)
        mm('speed', '10')  # the first phases use the Fast-end fixture
        mm('devices', ','.join(sorted(set(original_status['devices']) | {HL_NAME})))
        failures, phases = [], {}
        # Same Apple-fixture sequence with Hyprland choosing the accelerated and
        # the raw vector for its cursor move (input:force_no_accel false/true).
        for force in (False, True):
            set_force(force)
            name = f'force_no_accel_{str(force).lower()}'
            mm('trace', 'start', str(args.events + 100))
            mm('warp', str(start[0]), str(start[1]))
            if pos() != start:
                raise RuntimeError(f'warp failed: {pos()}')
            t0 = time.monotonic()
            send(mouse, inputs, args.interval_ms / 1000)
            elapsed = time.monotonic() - t0
            mm('trace', 'dump', str(work / f'{name}.csv'))
            all_rows = mx.read_trace(work / f'{name}.csv')
            rows = [r for r in all_rows if r['device'] == HL_NAME]
            foreign = [r for r in all_rows if r['device'] != HL_NAME]
            failures += [f'{name}: {f}' for f in mx.verify(rows, inputs, vectors, start)]
            if foreign:
                failures.append(f'{name}: {len(foreign)} events from other devices interleaved (user activity?) -> rerun')
            phases[name] = {'selected_events': len(rows), 'send_seconds': round(elapsed, 3)}

        # The remaining tracking-speed ticks, each against Apple's outputs for that tick.
        set_force(False)
        for tick in mx.TICKS:
            if tick == 10:
                continue
            if json.loads(mm('speed', str(tick)))['speed'] != tick:
                raise RuntimeError(f'cannot select speed {tick}')
            tick_vectors = mx.apple_vectors(tick)
            tick_inputs = mx.plan(tick_vectors, args.speed_events, start, box, seed=args.seed + tick)
            mm('trace', 'start', str(args.speed_events + 100))
            mm('warp', str(start[0]), str(start[1]))
            send(mouse, tick_inputs, args.interval_ms / 1000)
            mm('trace', 'dump', str(work / f'speed-{tick}.csv'))
            all_rows = mx.read_trace(work / f'speed-{tick}.csv')
            rows = [r for r in all_rows if r['device'] == HL_NAME]
            failures += [f'speed {tick}: {f}' for f in mx.verify(rows, tick_inputs, tick_vectors, start)]
            if len(rows) != len(all_rows):
                failures.append(f'speed {tick}: events from other devices interleaved (user activity?) -> rerun')
            phases[f'speed_{tick}'] = {'selected_events': len(rows)}
        set_force(force_original)

        # Unselected device: stock libinput acceleration must be untouched.
        mm('devices', ','.join(sorted(set(original_status['devices']) - {HL_NAME})))
        mm('trace', 'start', '500')
        mm('warp', str(start[0]), str(start[1]))
        stock_inputs = [k for k in inputs if k != (0, 0) and max(map(abs, k)) <= 6][:300]
        send(mouse, stock_inputs, args.interval_ms / 1000)
        mm('trace', 'dump', str(work / 'stock.csv'))
        stock = [r for r in mx.read_trace(work / 'stock.csv') if r['device'] == HL_NAME]
        if len(stock) != len(stock_inputs):
            failures.append(f'stock rows {len(stock)} != {len(stock_inputs)}')
        for i, (r, k) in enumerate(zip(stock, stock_inputs)):
            if r['kind'] != 3 or (r['raw_x'], r['raw_y']) != k or (r['applied_x'], r['applied_y']) != (r['stock_x'], r['stock_y']) \
                    or (r['after_x'], r['after_y']) != (r['before_x'] + r['stock_x'], r['before_y'] + r['stock_y']):
                failures.append(f'stock event {i} altered: {r}')
                break
        differs = sum(1 for r in stock if (r['stock_x'], r['stock_y']) != (0.0, 0.0))
        result = {
            'passed': not failures,
            'phases': phases, 'inputs_sent': len(inputs), 'zero_frames': inputs.count((0, 0)),
            'distinct_inputs': len(set(inputs)), 'physical_selected': args.physical,
            'stock_events': len(stock), 'stock_nonzero': differs,
            'monitor': {k: mon[k] for k in ('name', 'width', 'height', 'scale', 'x', 'y')}, 'start': start,
            'final_position': [x.hex() for x in pos()],
            'hyprland': ctl('version').splitlines()[0], 'plugin_status': json.loads(mm('status')),
            'failures': failures[:20], 'workdir': str(work),
        }
    finally:
        set_force(force_original)
        mm('speed', str(original_status['speed']))
        mouse.close()
        mm('devices', ','.join(original_status['devices']))
        mm('trace', 'stop')
        mm('warp', str(saved[0]), str(saved[1]))
        wait_device(False)
    text = json.dumps(result, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text + '\n')
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
