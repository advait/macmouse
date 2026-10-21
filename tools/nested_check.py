#!/usr/bin/env python3
"""Load macmouse into a new nested Hyprland and replay Apple-fixture inputs.

Isolation gate before loading into the live session: the nested instance has no
physical seat, its own config, and is terminated afterwards. Motion events are
emitted through installed Aquamarine/CMouse signals by the existing coordinate
probe plugin, so they reach the hooked CInputManager::onMouseMoved.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import expect as mx  # noqa: E402

ROOT = mx.ROOT
BUILD = ROOT / 'build'
PROBE_NAME = 'macmouse-test-probe'


def instances():
    return json.loads(subprocess.check_output(['hyprctl', '-j', 'instances'], text=True))


def ctl(instance, *args):
    return subprocess.run(['hyprctl', '-i', instance, *args], capture_output=True, text=True, check=True).stdout.strip()


def main():
    vectors = mx.apple_vectors()
    start = (1000.0, 600.0)
    inputs = mx.plan(vectors, 3000, start, (50, 50, 2510, 1390))
    baseline = {i['instance'] for i in instances()}
    env = dict(os.environ, LIBSEAT_BACKEND='macmouse-disabled', MACMOUSE_ISOLATED_TEST='1', HYPRLAND_NO_SD_NOTIFY='1')
    work = Path(tempfile.mkdtemp(prefix='macmouse-nested-'))
    log = open(work / 'hyprland.log', 'w')
    process = subprocess.Popen(['Hyprland', '--config', str(ROOT / 'tests/isolated-hyprland.conf')], env=env, stdout=log, stderr=subprocess.STDOUT)
    result = {'passed': False}
    try:
        instance = None
        for _ in range(200):
            found = [i for i in instances() if i['instance'] not in baseline and i['pid'] == process.pid]
            if found:
                instance = found[0]['instance']
                break
            time.sleep(0.05)
        if not instance:
            raise RuntimeError('nested Hyprland instance not found')
        time.sleep(1)
        assert ctl(instance, 'plugin', 'load', str(BUILD / 'probe_plugin.so')) == 'ok'
        loaded = ctl(instance, 'plugin', 'load', str(BUILD / 'macmouse.so'))
        assert loaded == 'ok', loaded
        status = json.loads(ctl(instance, 'macmouse', 'status'))
        assert status['selftest'] is True, status
        assert status['speed'] == 10, status  # default: the slider's Fast end
        ctl(instance, 'macmouse', 'devices', PROBE_NAME)

        def replay(rows, name, start_point):
            source = work / f'{name}.csv'
            with open(source, 'w') as f:
                f.write('index,x,y,dx,dy,time\n')
                for i, (x, y) in enumerate(rows):
                    # Stock fields are arbitrary libinput-like values the plugin must replace.
                    f.write(f'{i},{x},{y},{x * 0.71},{y * 0.71},{i * 1000}\n')
            out = ctl(instance, 'dispatch', 'macmousetest:coordinates', f'{source} {work / (name + "-probe.csv")} {start_point[0]} {start_point[1]}')
            assert out == 'ok', out

        failures = []
        for force in ('0', '1'):  # Hyprland moves by the accelerated vs raw vector
            assert ctl(instance, 'keyword', 'input:force_no_accel', force) == 'ok'
            ctl(instance, 'macmouse', 'trace', 'start', '100000')
            replay(inputs, f'selected-{force}', start)
            ctl(instance, 'macmouse', 'trace', 'dump', str(work / f'selected-{force}-trace.csv'))
            rows = [r for r in mx.read_trace(work / f'selected-{force}-trace.csv') if r['device'] == PROBE_NAME]
            failures += [f'force_no_accel={force}: {f}' for f in mx.verify(rows, inputs, vectors, start, zeros_delivered=True)]
        assert ctl(instance, 'keyword', 'input:force_no_accel', '0') == 'ok'

        # Every other tracking-speed tick: Apple's recorded outputs for that tick.
        speeds = {}
        for tick in mx.TICKS:
            if tick == 10:
                continue
            assert json.loads(ctl(instance, 'macmouse', 'speed', str(tick)))['speed'] == tick
            tick_vectors = mx.apple_vectors(tick)
            tick_inputs = mx.plan(tick_vectors, 600, start, (50, 50, 2510, 1390), seed=tick)
            ctl(instance, 'macmouse', 'trace', 'start', '1000')
            replay(tick_inputs, f'speed-{tick}', start)
            ctl(instance, 'macmouse', 'trace', 'dump', str(work / f'speed-{tick}-trace.csv'))
            trows = [r for r in mx.read_trace(work / f'speed-{tick}-trace.csv') if r['device'] == PROBE_NAME]
            failures += [f'speed {tick}: {f}' for f in mx.verify(trows, tick_inputs, tick_vectors, start, zeros_delivered=True)]
            speeds[tick] = len(trows)
        for bad in ('0', '11', '2.5', '-1', 'fast'):
            out = subprocess.run(['hyprctl', '-i', instance, 'macmouse', 'speed', bad], capture_output=True, text=True).stdout
            if 'speed must be' not in out:  # hyprctl exits nonzero on an error reply
                failures.append(f'speed {bad} accepted')
        if json.loads(ctl(instance, 'macmouse', 'status'))['speed'] != 9:
            failures.append('rejected speed changed the setting')
        assert json.loads(ctl(instance, 'macmouse', 'speed', '10'))['speed'] == 10

        # Passthrough: device not selected -> stock delta, untouched.
        ctl(instance, 'macmouse', 'devices', 'some-other-mouse')
        ctl(instance, 'macmouse', 'trace', 'start', '1000')
        other = [k for k in inputs if max(abs(k[0]), abs(k[1])) <= 6][:200]
        replay(other, 'other', start)
        ctl(instance, 'macmouse', 'trace', 'dump', str(work / 'other-trace.csv'))
        orows = mx.read_trace(work / 'other-trace.csv')
        pos = start
        for i, (r, k) in enumerate(zip(orows, other)):
            exp = (pos[0] + k[0] * 0.71, pos[1] + k[1] * 0.71)
            if r['kind'] != 3 or (r['applied_x'], r['applied_y']) != (k[0] * 0.71, k[1] * 0.71) or (r['after_x'], r['after_y']) != exp:
                failures.append(f'passthrough event {i} changed: {r}')
                break
            pos = exp
        if len(orows) != len(other):
            failures.append(f'passthrough rows {len(orows)} != {len(other)}')

        result = {'passed': not failures, 'selected_events': len(rows), 'speed_events': speeds, 'passthrough_events': len(orows),
                  'apple_fixture_inputs': len(inputs), 'distinct_inputs': len(set(inputs)),
                  'hyprland': ctl(instance, 'version').splitlines()[0], 'failures': failures[:20], 'workdir': str(work)}
    finally:
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
    print(json.dumps(result, indent=1))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
