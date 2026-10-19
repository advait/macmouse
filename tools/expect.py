"""Independent expectations for the macmouse plugin.

Table outputs come from the installed macOS accelerator's recorded results
(tests/apple-pointer-vectors.csv.gz), never from the plugin's C++ model. The
binary32 NX projection and WindowServer's truncating signed 24.8 cursor
feedback are recomputed here with Python binary64 arithmetic.
"""
import csv
import gzip
import random
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def apple_vectors():
    """Integer-count fixture rows: {(dx, dy): (out_x, out_y)} as Apple produced them."""
    table = {}
    with gzip.open(ROOT / 'tests/apple-pointer-vectors.csv.gz', 'rt') as f:
        for row in csv.DictReader(f):
            try:
                dx, dy = int(row['dx']), int(row['dy'])
            except ValueError:
                continue
            if abs(dx) > 32767 or abs(dy) > 32767:
                continue
            out = (float(row['out_dx']), float(row['out_dy']))
            if table.setdefault((dx, dy), out) != out:
                raise AssertionError(f'inconsistent Apple rows for {(dx, dy)}')
    return table


def f32(v):
    return struct.unpack('<f', struct.pack('<f', v))[0]


def f32_bits(v):
    return struct.unpack('<I', struct.pack('<f', v))[0]


def trunc_fixed(v):
    # static_cast<int32_t>(v * 256) / 256; Python int() truncates toward zero.
    return int(v * 256.0) / 256.0


def step(position, apple_out):
    """Expected (nx, next_position) for one admitted event, or next None for no motion."""
    nx = (f32(apple_out[0]), f32(apple_out[1]))
    if nx == (0.0, 0.0):
        return nx, None
    return nx, (trunc_fixed(position[0] + nx[0]), trunc_fixed(position[1] + nx[1]))


def plan(vectors, count, start, box, seed=1):
    """Pick fixture inputs whose predicted path stays strictly inside box (no clipping)."""
    rng = random.Random(seed)
    keys = sorted(vectors)
    small = [k for k in keys if max(abs(k[0]), abs(k[1])) <= 6]
    position, chosen = start, []
    x0, y0, x1, y1 = box
    for i in range(count):
        pool = small if i % 3 else keys  # mix slow, precise motion with fast swipes
        for _ in range(1000):
            k = rng.choice(pool)
            _, nxt = step(position, vectors[k])
            nxt = nxt or position
            if x0 < nxt[0] < x1 and y0 < nxt[1] < y1:
                chosen.append(k)
                position = nxt
                break
        else:
            raise RuntimeError('cannot plan an unclipped path')
    return chosen


def read_trace(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            for k in ('raw_x', 'raw_y', 'stock_x', 'stock_y', 'table_x', 'table_y', 'before_x', 'before_y',
                      'applied_x', 'applied_y', 'after_x', 'after_y'):
                r[k] = float.fromhex(r[k])
            r['kind'] = int(r['kind'])
            r['nx_x_bits'] = int(r['nx_x_bits'], 16)
            r['nx_y_bits'] = int(r['nx_y_bits'], 16)
            rows.append(r)
    return rows


def verify(rows, inputs, vectors, start, zeros_delivered=False):
    """Check a trace of selected-device rows against inputs sent from start. Returns list of failures.

    libinput emits no motion event for an all-zero frame; a direct IPointer probe does.
    """
    failures = []
    sent = [k for k in inputs if zeros_delivered or k != (0, 0)]
    if len(rows) != len(sent):
        return [f'event count {len(rows)} != nonzero inputs {len(sent)}']
    position = start
    for i, (row, k) in enumerate(zip(rows, sent)):
        out = vectors[k]
        nx, nxt = step(position, out)
        problems = []
        if (row['raw_x'], row['raw_y']) != (float(k[0]), float(k[1])):
            problems.append(f"raw {row['raw_x'], row['raw_y']} != {k}")
        if (row['table_x'], row['table_y']) != out:
            problems.append(f"table {row['table_x'].hex(), row['table_y'].hex()} != Apple {out[0].hex(), out[1].hex()}")
        if (row['nx_x_bits'], row['nx_y_bits']) != (f32_bits(nx[0]), f32_bits(nx[1])):
            problems.append('nx bits')
        if (row['before_x'], row['before_y']) != position:
            problems.append(f"before {row['before_x'], row['before_y']} != {position}")
        expected_after = nxt or position
        if (row['after_x'], row['after_y']) != expected_after:
            problems.append(f"after {row['after_x'].hex(), row['after_y'].hex()} != {expected_after[0].hex(), expected_after[1].hex()}")
        if (row['applied_x'], row['applied_y']) != ((0.0, 0.0) if nxt is None else (nxt[0] - position[0], nxt[1] - position[1])):
            problems.append('applied step')
        if row['kind'] != (1 if nxt is None else 0):
            problems.append(f"kind {row['kind']}")
        if problems:
            failures.append(f'event {i} input {k}: ' + '; '.join(problems))
            if len(failures) > 20:
                break
        position = expected_after
    return failures
