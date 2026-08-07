"""Layer 3 -- drawing primitives.

Free functions shared by every widget: axis ranges, number and time
formatting, and the two expensive conversions from columns of samples into
something Qt can draw. No widget state, no View, no Store -- everything comes
in as arguments, which is what makes the fiddly parts testable in isolation.

May import: palette.
"""

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QPen, QPolygonF

from .palette import MARKER, PANE_BG, alpha

# Gutters, identical in every pane so the columns line up. Read these as
# `render.LEFT`, never `from .render import LEFT`: calibrate() replaces them at
# startup and a from-import would bind the stale value.
#
# They were fixed pixel counts, tuned against a 7.5 pt label -- but the fonts
# are derived from the system's default size and scale with it and with DPI,
# while the gutters did not. On a desktop with a larger default font the row
# labels lost their first character ("PROCHOT CPU" rendered as "ROCHOT CPU")
# and end-of-line labels lost their last ("amdgpu hwmon" -> "amdgpu hwmor").
# Measuring the actual strings is the only thing that holds across machines.
LEFT = 72          # y-axis gutter, and the cap-reason / per-core row labels
RIGHT = 104        # room for end-of-line direct labels
HEADER_H = 26      # the header row of widgets above each painted body
TOP = 2            # breathing room at the top of the body itself
BOTTOM = 6

_DEFAULT_LEFT, _DEFAULT_RIGHT = LEFT, RIGHT


def pane_font():
    """The body font every pane and the axis use: one step below the system
    default, floored so it stays legible where that default is already small."""
    f = QFont()
    f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
    return f


def row_label_font():
    """Smaller again, for the raster row labels in the left gutter."""
    f = pane_font()
    f.setPointSizeF(max(6.5, f.pointSizeF() - 1.0))
    return f


def calibrate(font, row_labels, series_labels):
    """Widen the gutters until the widest label of each kind fits.

    Called once, after a QApplication exists so the metrics are real. Measured
    at the body font even for the raster rows, which are drawn a step smaller —
    over-provisioning by a few pixels is cheaper than another clipped label.

    Never narrows below the defaults: the left gutter also has to hold y-axis
    tick text, which is not known until there is data.
    """
    global LEFT, RIGHT
    fm = QFontMetrics(font)
    LEFT = max(_DEFAULT_LEFT,
               max((fm.horizontalAdvance(s) for s in row_labels), default=0)
               + 12)
    RIGHT = max(_DEFAULT_RIGHT,
                max((fm.horizontalAdvance(s) for s in series_labels),
                    default=0) + 20)
    return LEFT, RIGHT


def nice_range(lo, hi, floor0):
    """A stable, round-numbered axis range containing [lo, hi].

    Stability matters more than tightness on a live chart: an axis that
    re-fits every frame makes the trace appear to move when it has not. Round
    steps mean small excursions stay inside the current range.
    """
    if floor0:
        lo = min(0.0, lo)
    if not math.isfinite(lo) or not math.isfinite(hi):
        return 0.0, 1.0
    if hi - lo < 1e-9:
        hi = lo + max(1.0, abs(lo) * 0.1)
    pad = (hi - lo) * 0.08
    lo, hi = lo - (0.0 if floor0 and lo >= 0 else pad), hi + pad
    if floor0:
        lo = min(lo, 0.0)
    span = hi - lo
    step = 10.0 ** math.floor(math.log10(span / 3.0))
    for mult in (1, 2, 2.5, 5, 10):
        if span / (step * mult) <= 4.5:
            step *= mult
            break
    lo = math.floor(lo / step) * step
    hi = math.ceil(hi / step) * step
    return lo, hi


def fmt_val(v, unit):
    if v is None:
        return "--"
    a = abs(v)
    if unit == "V":
        return f"{v:.3f}"
    if unit in ("MHz", "rpm", "FIT", "level"):
        return f"{v:.0f}"
    if a >= 100:
        return f"{v:.0f}"
    if a >= 10:
        return f"{v:.1f}"
    return f"{v:.2f}"


def fmt_time(t):
    t = int(round(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def time_ticks(t0, t1):
    """Round time steps that stay put as the window scrolls.

    Shared by the chart panes' vertical gridlines and by the TimeAxis ruler,
    so the two cannot drift apart.
    """
    span = max(1e-6, t1 - t0)
    for step in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800,
                 3600, 7200, 21600, 43200, 86400):
        if span / step <= 9:
            break
    start = math.ceil(t0 / step) * step
    out = []
    t = start
    while t <= t1 and len(out) < 32:
        out.append(t)
        t += step
    return out


def draw_markers(p, view, r, x_of, label_them):
    """Vertical rules for manually placed events, on every pane so a marker
    lines up down the whole window. Only the topmost pane draws the text;
    repeating it once per pane would bury the data."""
    if not view.markers:
        return
    fm = QFontMetrics(p.font())
    for t, label in view.markers:
        x = float(x_of(t))
        if not (r.left() <= x <= r.right()):
            continue
        p.setPen(QPen(alpha(MARKER, 150), 1.0, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        if label_them and label:
            w = fm.horizontalAdvance(label) + 8
            bx = min(x + 3, r.right() - w)
            p.fillRect(QRectF(bx, r.top() + 1, w, fm.height()),
                       alpha(PANE_BG, 220))
            p.setPen(MARKER)
            p.drawText(QRectF(bx + 4, r.top() + 1, w, fm.height()),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter, label)


def column_hold(cols, vals, width):
    """Map samples onto pixel columns, each held until the next sample.

    Returns (values, valid_mask). Without the hold, a raster window wider than
    the sample count paints isolated one-pixel marks separated by background,
    which reads as an intermittent signal when it is really a continuous one
    sampled sparsely -- the same illusion, at the display layer, that the
    duty-cycle sampling fixes at the source. Nothing is painted past the last
    sample, so the future stays blank rather than being extrapolated.

    `cols` must be non-decreasing, which it is: it derives from sorted time.
    """
    out = np.zeros(width, dtype=np.float64)
    valid = np.zeros(width, dtype=bool)
    if cols.size == 0:
        return out, valid
    per = np.zeros(width, dtype=np.float64)
    np.maximum.at(per, cols, vals)          # worst wins a shared column
    seen = np.zeros(width, dtype=bool)
    seen[cols] = True
    ar = np.arange(width)
    src = np.maximum.accumulate(np.where(seen, ar, -1))
    valid = (src >= 0) & (ar <= cols[-1])
    out[valid] = per[src[valid]]
    return out, valid


def _runs(polys, xs, ys):
    """Append one polygon per contiguous run, given parallel Python lists."""
    if len(xs) == 1:
        # A lone sample would be invisible as a zero-length polyline.
        polys.append(QPolygonF([QPointF(xs[0], ys[0]),
                                QPointF(xs[0] + 0.6, ys[0])]))
    elif len(xs) > 1:
        polys.append(QPolygonF([QPointF(a, b) for a, b in zip(xs, ys)]))


def polylines(xpx, ypx, x_left, width_px):
    """Build screen-space polylines from pixel coordinates.

    Takes coordinates already projected into screen space rather than
    projection callables: doing the transform per point in Python cost more
    than Qt spent drawing the result, so both axes are mapped with a single
    numpy expression by the caller.

    Splits on NaN so a dropped sensor leaves a gap. Above roughly two samples
    per pixel the run is decimated to a per-column min/max envelope, which
    preserves spikes that plain subsampling would drop -- the spikes are
    usually the interesting part.
    """
    n = ypx.size
    if n == 0:
        return []
    good = np.isfinite(ypx) & np.isfinite(xpx)
    if not good.any():
        return []

    polys = []
    if n > 2 * max(1, width_px):
        # Columns are absolute pixel positions, not a rescale of the data's
        # own extent: a trace covering only part of the window has to stay
        # where it belongs on the shared time axis.
        cols = np.clip((xpx - x_left).astype(np.int64), 0, width_px - 1)
        cg, yg = cols[good], ypx[good]
        lo = np.full(width_px, np.inf)
        hi = np.full(width_px, -np.inf)
        np.minimum.at(lo, cg, yg)
        np.maximum.at(hi, cg, yg)
        filled = np.flatnonzero(np.isfinite(lo))
        if filled.size == 0:
            return []
        # One vertical span per column, chained; break where columns are not
        # adjacent so a gap in the data stays a gap on screen.
        brk = np.flatnonzero(np.diff(filled) > 1)
        for a, b in zip(np.concatenate(([0], brk + 1)),
                        np.concatenate((brk + 1, [filled.size]))):
            seg = filled[a:b]
            cx = (seg + x_left).astype(np.float64)
            xs, los, his = cx.tolist(), lo[seg].tolist(), hi[seg].tolist()
            pts = []
            for x, l, h in zip(xs, los, his):
                pts.append(QPointF(x, l))
                pts.append(QPointF(x, h))
            if len(pts) >= 2:
                polys.append(QPolygonF(pts))
        return polys

    # Contiguous runs of finite samples, drawn as-is. .tolist() first: iterating
    # numpy scalars costs several times more than iterating Python floats.
    idx = np.flatnonzero(good)
    brk = np.flatnonzero(np.diff(idx) > 1)
    for a, b in zip(np.concatenate(([0], brk + 1)),
                    np.concatenate((brk + 1, [idx.size]))):
        run = idx[a:b]
        _runs(polys, xpx[run].tolist(), ypx[run].tolist())
    return polys
