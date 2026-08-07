"""Layer 4 -- the two raster strip charts.

Both answer a question that too many series would only obscure: which of
thirteen throttler reasons fired, and how load sat across the detected cores.
Both paint a row-per-thing QImage the width of the plot rather than thousands
of primitives, which is what keeps a full-window repaint cheap.

May import: fields, palette, panes, render, timepane.
"""

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QComboBox

from . import render
from .frame import PaneFrame, Readout
from .fields import N_CORES, THROTTLE_BITS
from .palette import (CRITICAL, INK, INK_DIM, LUT, MUTED, PANE_BG, RAMP,
                      SERIES, alpha)
from .panes import CAP_DEFAULT, CAP_RATES, HEAT_MODES
from .render import column_hold, draw_markers, fmt_val, row_label_font
from .timepane import TimePane


class ThrottlePane(TimePane):
    """One row per SMU throttler bit, lit where that reason was active.

    This is the pane the rest of the window exists to explain. Thirteen
    reasons is far past where categorical colour stays separable, so identity
    comes from the row label and the fixed vertical order; colour only groups
    them into families, and PROCHOT gets the reserved critical step because it
    means an agent outside the SMU pulled the brake.

    Currently-active reasons are also spelled out in the header, in words --
    a lit cell in a raster is easy to miss, and the whole point is not to miss
    it.
    """

    ROW = 11
    FAMILY = {"power": QColor(SERIES[0]), "thermal": QColor(SERIES[1]),
              "current": QColor(SERIES[2]), "prochot": CRITICAL}

    # The poll rate lives here rather than in the toolbar: this is the only
    # pane it affects, and the percentages in the header are meaningless
    # without it, so it is printed alongside them and changed by right-click.
    capRateChanged = pyqtSignal(float)

    def __init__(self, view, parent=None):
        super().__init__(view, parent)
        self.cap_hz = CAP_RATES[CAP_DEFAULT][0]
        self._buf = None
        # Row labels get their own smaller font: "PROCHOT CPU" is the longest
        # name here and does not fit the shared gutter at body size. The gutter
        # itself is sized from these strings at startup -- see
        # render.calibrate() -- because it has to be the same in every pane.
        self.label_font = row_label_font()
        # ROW is a data-density choice, but it also has to hold a line of text,
        # and 11 px was already a pixel short of the label at the smallest font
        # this program uses. It grows with the font rather than clipping.
        self.ROW = max(ThrottlePane.ROW,
                       QFontMetrics(self.label_font).height())
        self.fix_height(render.TOP + len(THROTTLE_BITS) * self.ROW + 8)

    def plot_rect(self):
        left = self.gutter_left()
        return QRectF(left, render.TOP,
                      max(10, self.width() - left - render.RIGHT),
                      len(THROTTLE_BITS) * self.ROW)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), PANE_BG)
        r = self.plot_rect()
        self._draw_image(p, r, self.view.store)

        p.setFont(self.label_font)
        for i, (_bit, name, fam) in enumerate(THROTTLE_BITS):
            y = r.top() + i * self.ROW
            p.setPen(alpha(self.FAMILY[fam], 210))
            p.drawText(QRectF(0, y, self.gutter_left() - 4, self.ROW),
                       Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, name)
        p.setFont(self.font())

        draw_markers(p, self.view, r, self.x_of, self.label_markers)
        self.draw_cursor_rule(p, r)
        self.draw_selection(p, r)
        p.end()

    def _set_cap_rate(self, hz):
        self.cap_hz = hz
        self.capRateChanged.emit(hz)
        self.update()

    def _draw_image(self, p, r, store):
        n = len(THROTTLE_BITS)
        w = max(1, int(r.width()))
        img = np.zeros((n, w, 4), dtype=np.uint8)
        img[:, :, :] = (PANE_BG.blue(), PANE_BG.green(), PANE_BG.red(), 255)

        if store.n:
            ts = store.times()
            i0 = int(np.searchsorted(ts, self.view.t0, side="left"))
            i1 = int(np.searchsorted(ts, self.view.t1, side="right"))
            if i1 > i0:
                span = max(1e-9, self.view.t1 - self.view.t0)
                cols = np.clip((((ts[i0:i1] - self.view.t0) / span)
                                * (w - 1)).astype(np.int64), 0, w - 1)
                bg = np.array([PANE_BG.blue(), PANE_BG.green(),
                               PANE_BG.red()], dtype=np.float64)
                for i, (bit, _name, fam) in enumerate(THROTTLE_BITS):
                    a = store.col(f"thr{bit}")
                    if a is None:
                        continue
                    duty = np.nan_to_num(a[i0:i1].astype(np.float64), nan=0.0)
                    if not (duty > 0).any():
                        continue
                    acc, valid = column_hold(cols, duty, w)
                    lit = valid & (acc > 0)
                    if not lit.any():
                        continue
                    # sqrt, not linear: a 10% duty is meaningful and would be
                    # near-invisible against the surface at linear intensity.
                    # Exact figures live in the header, so this only has to be
                    # monotonic and legible.
                    inten = np.sqrt(np.clip(acc[lit], 0.0, 1.0))[:, None]
                    c = self.FAMILY[fam]
                    fg = np.array([c.blue(), c.green(), c.red()],
                                  dtype=np.float64)
                    img[i, lit, :3] = (bg + (fg - bg) * inten).astype(np.uint8)
        self.blit_rows(p, r, img, self.ROW)


class CorePane(TimePane):
    """One row per physical core, colour = the selected metric.

    Modern core counts are past where categorical colours stay separable, so
    this is a single-hue sequential encoding instead of eight lines: magnitude
    is the whole message, and identity comes from the row you are looking at.
    """

    ROW = 13

    def __init__(self, view, parent=None, core_count=N_CORES):
        super().__init__(view, parent)
        self.core_count = max(1, min(N_CORES, int(core_count)))
        self.mode = 0
        self._buf = None
        fm = QFontMetrics(self.font())
        self.ROW = max(CorePane.ROW, fm.height())
        # Under the rows: the colour bar and its range, whichever is taller.
        self._bar_h = 5 + max(self.BAR_H, fm.height()) + 3
        self.fix_height(render.TOP + self.core_count * self.ROW + self._bar_h)

    def set_core_count(self, core_count):
        """Resize the raster when switching between hosts or recordings."""
        self.core_count = max(1, min(N_CORES, int(core_count)))
        self.fix_height(render.TOP + self.core_count * self.ROW + self._bar_h)
        self.update()

    def set_mode(self, i):
        self.mode = i
        self.update()

    def plot_rect(self):
        left = self.gutter_left()
        return QRectF(left, render.TOP,
                      max(10, self.width() - left - render.RIGHT),
                      self.core_count * self.ROW)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), PANE_BG)
        base, _name, unit, dlo, dhi = HEAT_MODES[self.mode]
        r = self.plot_rect()

        lo, hi = self._draw_image(p, r, self.view.store, base, dlo, dhi)

        store, t = self.view.store, self.view.cursor
        for c in range(self.core_count):
            y = r.top() + c * self.ROW
            p.setPen(MUTED)
            p.drawText(QRectF(0, y, self.gutter_left() - 8, self.ROW),
                       Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, f"core {c}")
            # The value at the end of the row it belongs to, the way a chart
            # pane labels the end of each trace. Eight numbers in one header
            # strip only ever fitted four and a half of them, and put each one
            # nowhere near the core it described.
            v = (store.at(f"{base}_{c}", t) if t is not None
                 else store.latest(f"{base}_{c}"))
            if v is not None:
                p.setPen(INK_DIM)
                p.drawText(QRectF(r.right() + 6, y,
                                  self.width() - r.right() - 12, self.ROW),
                           Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter, fmt_val(v, unit))

        self._draw_colorbar(p, r, lo, hi, unit)

        draw_markers(p, self.view, r, self.x_of, self.label_markers)
        self.draw_cursor_rule(p, r)
        self.draw_selection(p, r)
        p.end()

    def _draw_image(self, p, r, store, base, dlo, dhi):
        w = max(1, int(r.width()))
        img = np.zeros((self.core_count, w, 4), dtype=np.uint8)
        img[:, :, :] = (PANE_BG.blue(), PANE_BG.green(), PANE_BG.red(), 255)

        if store.n:
            ts = store.times()
            i0 = int(np.searchsorted(ts, self.view.t0, side="left"))
            i1 = int(np.searchsorted(ts, self.view.t1, side="right"))
            if i1 > i0:
                span = max(1e-9, self.view.t1 - self.view.t0)
                cols = np.clip((((ts[i0:i1] - self.view.t0) / span)
                                * (w - 1)).astype(int), 0, w - 1)
                # Auto-scale to what is on screen, but never let the range
                # collapse: a flat window would otherwise paint full-scale
                # noise across every core.
                vis = []
                for c in range(self.core_count):
                    a = store.col(f"{base}_{c}")
                    if a is not None:
                        seg = a[i0:i1]
                        vis.append(seg[~np.isnan(seg)])
                allv = np.concatenate(vis) if vis else np.array([])
                if allv.size:
                    lo, hi = float(allv.min()), float(allv.max())
                    if hi - lo < (dhi - dlo) * 0.05:
                        mid = (lo + hi) / 2
                        half = (dhi - dlo) * 0.025
                        lo, hi = mid - half, mid + half
                else:
                    lo, hi = dlo, dhi
                for c in range(self.core_count):
                    a = store.col(f"{base}_{c}")
                    if a is None:
                        continue
                    seg = a[i0:i1].astype(np.float64)
                    ok = ~np.isnan(seg)
                    if not ok.any():
                        continue
                    norm = np.clip((seg - lo) / max(1e-9, hi - lo), 0, 1)
                    held, valid = column_hold(cols[ok], norm[ok], w)
                    if not valid.any():
                        continue
                    shade = (held * 255).astype(np.uint8)
                    img[c, valid] = LUT[shade[valid]]
                self.blit_rows(p, r, img, self.ROW)
                return lo, hi
        self.blit_rows(p, r, img, self.ROW)
        return dlo, dhi

    BAR_H = 8
    BAR_W = 88

    def _draw_colorbar(self, p, r, lo, hi, unit):
        fm = QFontMetrics(self.font())
        y = r.bottom() + 5
        x = r.left()
        for i in range(self.BAR_W):
            p.setPen(QColor(RAMP[min(len(RAMP) - 1,
                                     int(i / self.BAR_W * len(RAMP)))]))
            p.drawLine(QPointF(x + i, y), QPointF(x + i, y + self.BAR_H))
        p.setPen(MUTED)
        txt = f"{fmt_val(lo, unit)} → {fmt_val(hi, unit)} {unit}"
        # Measured, not a fixed 160 px: that box held the text at the smallest
        # font and cut it off above about 14 pt.
        p.drawText(QRectF(x + self.BAR_W + 6, y - 2,
                          fm.horizontalAdvance(txt) + 4, fm.height()),
                   Qt.AlignmentFlag.AlignLeft, txt)


class ThrottleReadout(Readout):
    """Which reasons are asserted, in words and as a percentage.

    A lit cell in a raster is easy to miss and the whole point is not to miss
    it. The percentage matters as much as the name: a reason asserted 8% of the
    interval is a different situation from one asserted 95%, and both render as
    a lit row.
    """

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.setMinimumWidth(160)

    def entries(self):
        store, t = self.view.store, self.view.cursor
        out = []
        for bit, name, fam in THROTTLE_BITS:
            v = (store.at(f"thr{bit}", t) if t is not None
                 else store.latest(f"thr{bit}"))
            if v:
                out.append((name, fam, v))
        out.sort(key=lambda a: -a[2])
        return out

    def draw(self, p, r):
        fm = QFontMetrics(self.font())
        active = self.entries()
        if not active:
            p.setPen(MUTED)
            p.drawText(r, Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter,
                       "none — nothing is holding it back")
            return
        x = r.right()
        for name, fam, v in active:
            txt = f"◀ {name} {v * 100:.0f}%"
            w = fm.horizontalAdvance(txt) + 12
            if x - w < r.left():
                break
            x -= w
            p.setPen(ThrottlePane.FAMILY[fam])
            p.drawText(QRectF(x, r.top(), w, r.height()),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter, txt)


def _combo(items, current, apply):
    box = QComboBox()
    for label in items:
        box.addItem(label)
    box.setCurrentIndex(current)
    box.currentIndexChanged.connect(apply)
    box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return box


def throttle_frame(view, indent=0):
    """The cap-reason strip, its poll-rate control, and its readout.

    The rate is a visible combo rather than a hidden context menu because the
    duty cycles beside it are meaningless without knowing what they were
    measured over.
    """
    body = ThrottlePane(view)
    rates = _combo([lbl for _hz, lbl in CAP_RATES], CAP_DEFAULT,
                   lambda i: body._set_cap_rate(CAP_RATES[i][0]))
    rates.setToolTip(
        "How often the throttler bitmask is sampled. The bits toggle at "
        "roughly 20 Hz, so 1 Hz reports a coin flip rather than a duty cycle, "
        "and switches the background thread off. ~1.2% of a core at 20 Hz.")
    frame = PaneFrame(body, "Cap reason", controls=[rates],
                      readout=ThrottleReadout(view),
                      height=render.HEADER_H + body.minimumHeight(),
                      indent=indent)
    frame.rates = rates
    return frame


def core_frame(view, indent=0, core_count=N_CORES):
    """The per-core strip and the selector for what its colour means.

    The title is just "Per-core": the combo beside it names the metric and its
    unit, and a title that repeated them would be stating the same fact twice
    in one row -- which is what the toolbar version was doing from across the
    window.
    """
    body = CorePane(view, core_count=core_count)
    modes = _combo([f"{n} ({u})" for _k, n, u, _l, _h in HEAT_MODES], 0,
                   body.set_mode)
    frame = PaneFrame(body, "Per-core", controls=[modes],
                      height=render.HEADER_H + body.minimumHeight(),
                      indent=indent)
    frame.modes = modes
    return frame
