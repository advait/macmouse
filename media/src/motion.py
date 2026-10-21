"""The shared synthetic hand motion: 1600 CPI mouse reports at 1000 Hz.

Minimum-jerk reaches (the standard model of human pointing), sampled every
millisecond and quantized like a sensor (cumulative position rounded to counts).
"""
import math

GESTURES = [  # (label, dx counts, dy counts, duration s, arc bulge counts, pause after s)
    ('slow', 700, 160, 1.6, 0, 0.6),
    ('flick', -950, -420, 0.20, 0, 0.6),
    ('arc', 1000, 520, 0.55, 260, 0.6),
    ('return', -560, -300, 1.3, 0, 0.0),
]


def minjerk(s):
    return 10 * s**3 - 15 * s**4 + 6 * s**5


def reports():
    """List of (dx, dy) per millisecond, and gesture spans [(label, start_ms, end_ms)]."""
    out, spans, fx, fy = [], [], 0.0, 0.0
    for label, dx, dy, dur, bulge, pause in GESTURES:
        n = round(dur * 1000)
        start = len(out)
        length = math.hypot(dx, dy)
        px, py = -dy / length, dx / length  # perpendicular for arcs
        bx0, by0 = fx, fy
        cx, cy = round(fx), round(fy)
        for i in range(1, n + 1):
            s = minjerk(i / n)
            arc = bulge * math.sin(math.pi * i / n)
            fx, fy = bx0 + dx * s + px * arc, by0 + dy * s + py * arc
            nx, ny = round(fx), round(fy)
            out.append((nx - cx, ny - cy))
            cx, cy = nx, ny
        spans.append((label, start, len(out)))
        out.extend([(0, 0)] * round(pause * 1000))
    return out, spans
