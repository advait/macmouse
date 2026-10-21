#!/usr/bin/env python3
"""Record real cursor paths for the demo video in the live Hyprland session.

Plays media/src/motion.py through a uinput virtual mouse twice: once with
stock libinput acceleration (device not selected) and once through macmouse.
Positions come from macmouse's trace of Hyprland's actual cursor. The macOS
reference path is computed from Apple's recorded accelerator outputs.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1] / 'tools')]
import expect as mx  # noqa: E402
import live_verify as lv  # noqa: E402
import motion  # noqa: E402

START = (1400.0, 720.0)


def play(mouse, reports):
    t0 = time.perf_counter() + 0.05
    for i, (dx, dy) in enumerate(reports):
        while time.perf_counter() < t0 + i / 1000:
            pass
        if dx or dy:
            mouse.move(dx, dy)
    time.sleep(0.3)


def phase(mouse, reports, selected, work, name):
    status = json.loads(lv.mm('status'))
    devices = set(status['devices']) - {lv.HL_NAME}
    if selected:
        devices.add(lv.HL_NAME)
    lv.mm('devices', ','.join(sorted(devices)) or '-')
    lv.mm('trace', 'start', str(len(reports) + 100))
    lv.mm('warp', str(START[0]), str(START[1]))
    play(mouse, reports)
    lv.mm('trace', 'dump', str(work / f'{name}.csv'))
    rows = [r for r in mx.read_trace(work / f'{name}.csv') if r['device'] == lv.HL_NAME]
    nonzero = [i for i, k in enumerate(reports) if k != (0, 0)]
    if len(rows) != len(nonzero):
        raise RuntimeError(f'{name}: {len(rows)} events for {len(nonzero)} reports')
    path, p, j = [], START, 0
    for i in range(len(reports)):
        if j < len(nonzero) and nonzero[j] == i:
            p = (rows[j]['after_x'], rows[j]['after_y'])
            j += 1
        path.append(p)
    return path


def main():
    reports, spans = motion.reports()
    vectors = mx.apple_vectors()
    mac, p = [], START
    for k in reports:
        _, nxt = mx.step(p, vectors[k])
        p = nxt or p
        mac.append(p)
    saved = lv.pos()
    original_sens = float(lv.ctl('getoption', 'input:sensitivity').splitlines()[0].split()[-1])
    original = json.loads(lv.mm('status'))['devices']
    work = Path(tempfile.mkdtemp(prefix='macmouse-demo-'))
    mouse = lv.VirtualMouse(lv.NAME)
    try:
        lv.wait_device(True)
        time.sleep(1.0)
        for _ in range(10):  # wake DPMS before recording (see VERIFICATION.md)
            mouse.move(1, 0); time.sleep(0.01); mouse.move(-1, 0); time.sleep(0.01)
        time.sleep(2.0)
        # "Stock Omarchy" means Omarchy's default input config (sensitivity 0,
        # adaptive profile), not the local user override.
        lv.ctl('eval', 'hl.config({input={sensitivity=0}})')
        time.sleep(0.5)
        stock_sens = lv.ctl('getoption', 'input:sensitivity').splitlines()[0]
        stock = phase(mouse, reports, False, work, 'stock')
        macmouse = phase(mouse, reports, True, work, 'macmouse')
    finally:
        lv.ctl('eval', f'hl.config({{input={{sensitivity={original_sens}}}}})')
        mouse.close()
        lv.mm('devices', ','.join(original) or '-')
        lv.mm('trace', 'stop')
        lv.mm('warp', str(saved[0]), str(saved[1]))
    exact = sum(a == b for a, b in zip(macmouse, mac))
    prof = lv.ctl('getoption', 'input:accel_profile').splitlines()[0]
    out = {'start': START, 'hz': 1000, 'spans': spans, 'reports': reports,
           'mac': mac, 'macmouse': macmouse, 'stock': stock,
           'stock_config': f'libinput, input:sensitivity {stock_sens}, accel_profile {prof}',
           'macmouse_equals_mac_samples': f'{exact}/{len(mac)}'}
    Path(sys.argv[1] if len(sys.argv) > 1 else 'demo-data.json').write_text(json.dumps(out))
    print(out['stock_config'], out['macmouse_equals_mac_samples'])


if __name__ == '__main__':
    main()
