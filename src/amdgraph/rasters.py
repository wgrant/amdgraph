"""Layer 4 -- the two raster strip charts.

Both answer a question that too many series would only obscure: which of
thirteen throttler reasons fired, and how the load sat across eight cores.
Both paint a row-per-thing QImage the width of the plot rather than thousands
of primitives, which is what keeps a full-window repaint cheap.

May import: fields, palette, panes, render, timepane.
"""

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QMenu

from . import render
from .fields import N_CORES, THROTTLE_BITS
from .palette import (CRITICAL, INK, INK_DIM, LUT, MUTED, PANE_BG, RAMP,
                      SERIES, alpha)
from .panes import CAP_DEFAULT, CAP_RATES, HEAT_MODES
from .render import TOP, column_hold, draw_markers, fmt_val, row_label_font
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
        self.fix_height(TOP + len(THROTTLE_BITS) * self.ROW + 8)
        self._buf = None
        # Row labels get their own smaller font: "PROCHOT CPU" is the longest
        # name here and does not fit the shared gutter at body size. The gutter
        # itself is sized from these strings at startup -- see
        # render.calibrate() -- because it has to be the same in every pane.
        self.label_font = row_label_font()

    def plot_rect(self):
        return QRectF(render.LEFT, TOP,
                      max(10, self.width() - render.LEFT - render.RIGHT),
                      len(THROTTLE_BITS) * self.ROW)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), PANE_BG)
        r = self.plot_rect()
        store = self.view.store
        fm = QFontMetrics(self.font())

        self._draw_image(p, r, store)

        p.setFont(self.label_font)
        for i, (_bit, name, fam) in enumerate(THROTTLE_BITS):
            y = r.top() + i * self.ROW
            p.setPen(alpha(self.FAMILY[fam], 210))
            p.drawText(QRectF(0, y, render.LEFT - 4, self.ROW),
                       Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, name)
        p.setFont(self.font())

        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(INK)
        p.drawText(QRectF(6, 2, 200, TOP - 4),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Cap reason")
        p.setFont(self.font())

        # The rate the duty cycles below are measured over. Without it a "62%"
        # is uninterpretable, and it is also the affordance for changing it.
        rate = f"{self.cap_hz:g} Hz"
        p.setPen(MUTED)
        rx = 6 + fm.horizontalAdvance("Cap reason") + 10
        p.drawText(QRectF(rx, 2, fm.horizontalAdvance(rate) + 4, TOP - 4),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   rate)

        # Spell out what is active right now (or under the crosshair).
        t = self.view.cursor
        active = []
        for bit, name, fam in THROTTLE_BITS:
            v = (store.at(f"thr{bit}", t) if t is not None
                 else store.latest(f"thr{bit}"))
            if v:
                active.append((name, fam, v))
        active.sort(key=lambda a: -a[2])
        x = rx + fm.horizontalAdvance(rate) + 14
        if not active:
            p.setPen(MUTED)
            p.drawText(QRectF(x, 2, 300, TOP - 4),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter,
                       "none — nothing is holding it back")
        else:
            for name, fam, v in active:
                # The percentage is the point: a reason asserted 8% of the
                # interval is a different situation from one asserted 95%,
                # and both used to render identically.
                txt = f"◀ {name} {v * 100:.0f}%"
                w = fm.horizontalAdvance(txt) + 12
                if x + w > self.width() - 6:
                    break
                p.setPen(self.FAMILY[fam])
                p.drawText(QRectF(x, 2, w, TOP - 4),
                           Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter, txt)
                x += w

        draw_markers(p, self.view, r, self.x_of, self.label_markers)
        self.draw_cursor_rule(p, r)
        self.draw_selection(p, r)
        p.end()

    def contextMenuEvent(self, ev):
        """Right-click picks the poll rate.

        The bits are instantaneous flags on a controller that duty-cycles at
        roughly 20 Hz, so 1 Hz reports a coin flip rather than a duty cycle,
        and 1 Hz also switches the background thread off entirely. Higher
        costs more CPU -- about 1.2% of a core at 20 Hz.
        """
        menu = QMenu(self)
        menu.addAction("Cap poll rate").setEnabled(False)
        menu.addSeparator()
        for hz, label in CAP_RATES:
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(hz == self.cap_hz)
            act.triggered.connect(lambda _c, v=hz: self._set_cap_rate(v))
        menu.exec(ev.globalPos())

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

    Eight cores is past the point where categorical colours stay separable, so
    this is a single-hue sequential encoding instead of eight lines: magnitude
    is the whole message, and identity comes from the row you are looking at.
    """

    ROW = 13

    def __init__(self, view, parent=None):
        super().__init__(view, parent)
        self.mode = 0
        self.fix_height(TOP + N_CORES * self.ROW + 18)
        self._buf = None

    def set_mode(self, i):
        self.mode = i
        self.update()

    def plot_rect(self):
        return QRectF(render.LEFT, TOP,
                      max(10, self.width() - render.LEFT - render.RIGHT),
                      N_CORES * self.ROW)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), PANE_BG)
        base, name, unit, dlo, dhi = HEAT_MODES[self.mode]
        r = self.plot_rect()
        store = self.view.store
        fm = QFontMetrics(self.font())

        lo, hi = self._draw_image(p, r, store, base, dlo, dhi)

        p.setPen(MUTED)
        for c in range(N_CORES):
            y = r.top() + c * self.ROW
            p.drawText(QRectF(0, y, render.LEFT - 8, self.ROW),
                       Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, f"core {c}")

        # Header: title, then per-core readout at the crosshair.
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(INK)
        p.drawText(QRectF(6, 2, 300, TOP - 4),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"Per-core {name}  ({unit})")
        p.setFont(self.font())

        t = self.view.cursor
        vals = []
        for c in range(N_CORES):
            v = (store.at(f"{base}_{c}", t) if t is not None
                 else store.latest(f"{base}_{c}"))
            vals.append(v)
        txt = "  ".join(fmt_val(v, unit) for v in vals if v is not None)
        if txt:
            p.setPen(INK_DIM)
            p.drawText(QRectF(self.width() - 8 - fm.horizontalAdvance(txt), 2,
                              fm.horizontalAdvance(txt) + 2, TOP - 4),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter, txt)

        self._draw_colorbar(p, r, lo, hi, unit)

        draw_markers(p, self.view, r, self.x_of, self.label_markers)
        self.draw_cursor_rule(p, r)
        self.draw_selection(p, r)
        p.end()

    def _draw_image(self, p, r, store, base, dlo, dhi):
        w = max(1, int(r.width()))
        img = np.zeros((N_CORES, w, 4), dtype=np.uint8)
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
                for c in range(N_CORES):
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
                for c in range(N_CORES):
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

    def _draw_colorbar(self, p, r, lo, hi, unit):
        fm = QFontMetrics(self.font())
        y = r.bottom() + 5
        bw, bh = 88, 8
        x = r.left()
        for i in range(bw):
            p.setPen(QColor(RAMP[min(len(RAMP) - 1,
                                     int(i / bw * len(RAMP)))]))
            p.drawLine(QPointF(x + i, y), QPointF(x + i, y + bh))
        p.setPen(MUTED)
        p.drawText(QRectF(x + bw + 6, y - 2, 160, fm.height()),
                   Qt.AlignmentFlag.AlignLeft,
                   f"{fmt_val(lo, unit)} → {fmt_val(hi, unit)} {unit}")
