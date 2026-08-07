"""Layer 5 -- the line-chart pane.

One PaneSpec in, one strip chart out. This is where a spec's series, ceilings
and note become pixels; it holds no knowledge of what any particular key means.

May import: palette, panes, render, timepane.
"""

import math

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen

from . import render
from .frame import PaneFrame, Readout
from .palette import (AXIS, CRITICAL, GRID, INK, INK_DIM, MUTED, PANE_BG,
                      SERIES, WARNING, alpha)
from .render import (draw_markers, fmt_val, nice_range, polylines,
                     time_ticks)
from .timepane import TimePane


class ChartPane(TimePane):

    def __init__(self, spec, view, parent=None):
        super().__init__(view, parent)
        self.spec = spec
        self.fix_height(spec.height)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pan_from = None
        self._rect = None
        self._ylo, self._yhi = 0.0, 1.0

    # -- geometry ---------------------------------------------------------

    def resizeEvent(self, ev):
        self._rect = None
        super().resizeEvent(ev)

    def plot_rect(self):
        # Cached, and rebuilt only on resize. This used to allocate a QRectF
        # per call, and y_of() calls it once per plotted point -- it was the
        # single largest cost in a repaint.
        if self._rect is None:
            left = self.gutter_left()
            self._rect = QRectF(
                left, render.TOP,
                max(10, self.width() - left - render.RIGHT),
                max(10, self.height() - render.TOP - render.BOTTOM))
        return self._rect

    def y_of(self, v):
        r = self.plot_rect()
        span = max(1e-9, self._yhi - self._ylo)
        return r.bottom() - (v - self._ylo) / span * r.height()

    # -- data -------------------------------------------------------------

    def _visible_series(self):
        return [(i, s) for i, s in enumerate(self.spec.series) if s.visible]

    def _index_range(self, store):
        ts = store.times()
        if ts.size == 0:
            return 0, 0
        i0 = int(np.searchsorted(ts, self.view.t0, side="left"))
        i1 = int(np.searchsorted(ts, self.view.t1, side="right"))
        return max(0, i0 - 1), min(ts.size, i1 + 1)

    def _fit_y(self):
        lo, hi = math.inf, -math.inf
        for store in (self.view.store, self.view.overlay):
            if store is None or store.n == 0:
                continue
            i0, i1 = self._index_range(store)
            if i1 <= i0:
                continue
            for _, s in self._visible_series():
                for key in (s.key, s.limit):
                    if not key:
                        continue
                    a = store.col(key)
                    if a is None:
                        continue
                    seg = a[i0:i1]
                    seg = seg[~np.isnan(seg)]
                    if seg.size:
                        lo = min(lo, float(seg.min()))
                        hi = max(hi, float(seg.max()))
        if lo is math.inf:
            self._ylo, self._yhi = (0.0, 1.0)
            return False
        self._ylo, self._yhi = nice_range(lo, hi, self.spec.floor0)
        return True

    # -- painting ---------------------------------------------------------

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), PANE_BG)
        have = self._fit_y()
        r = self.plot_rect()

        self._draw_grid(p, r, have)
        if have:
            if self.view.overlay is not None:
                self._draw_store(p, r, self.view.overlay, ghost=True)
            self._draw_store(p, r, self.view.store, ghost=False)
            self._draw_end_labels(p, r)
        draw_markers(p, self.view, r, self.x_of, self.label_markers)
        self._draw_cursor(p, r)
        self.draw_selection(p, r)
        p.end()

    def _draw_grid(self, p, r, have):
        p.setPen(QPen(AXIS, 1))
        p.drawLine(QPointF(r.left(), r.top()), QPointF(r.left(), r.bottom()))
        if not have:
            p.setPen(MUTED)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "no data")
            return
        step = (self._yhi - self._ylo) / 4.0
        fm = QFontMetrics(self.font())
        v = self._ylo
        while v <= self._yhi + step * 0.01:
            y = self.y_of(v)
            p.setPen(QPen(GRID, 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(MUTED)
            txt = fmt_val(v, self.spec.unit)
            p.drawText(QRectF(0, y - fm.height() / 2, self.gutter_left() - 8,
                              fm.height()),
                       Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, txt)
            v += step
        # Vertical gridlines share their positions with the time axis widget.
        p.setPen(QPen(GRID, 1))
        for t in time_ticks(self.view.t0, self.view.t1):
            x = float(self.x_of(t))
            if r.left() < x < r.right():
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

    def _draw_store(self, p, r, store, ghost):
        if store.n == 0:
            return
        i0, i1 = self._index_range(store)
        if i1 <= i0:
            return
        ts = store.times()
        w = int(r.width())
        # Project both axes once per series with a single numpy expression.
        xsc = r.width() / max(1e-9, self.view.t1 - self.view.t0)
        ysc = r.height() / max(1e-9, self._yhi - self._ylo)
        xpx = r.left() + (ts[i0:i1] - self.view.t0) * xsc
        p.setClipRect(r)
        for i, s in self._visible_series():
            a = store.col(s.key)
            if a is None:
                continue
            ypx = r.bottom() - (a[i0:i1].astype(np.float64) - self._ylo) * ysc
            col = QColor(SERIES[i % len(SERIES)])
            if ghost:
                # The reloaded run sits behind the live one at low alpha and
                # hairline weight: present enough to compare against, never
                # competing with the trace you are actually watching.
                pen = QPen(alpha(col, 92), 1.0)
            else:
                pen = QPen(col, 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            for poly in polylines(xpx, ypx, r.left(), w):
                p.drawPolyline(poly)

            # The limit, as the time series it actually is. It used to be a
            # flat line at whatever the limit read *now*, drawn across the
            # whole window -- which silently redrew history against a ceiling
            # that was not in force at the time. On this machine the ceilings
            # move constantly, so that was not a hypothetical error.
            if s.limit and not ghost:
                la = store.col(s.limit)
                if la is not None:
                    lypx = (r.bottom()
                            - (la[i0:i1].astype(np.float64) - self._ylo) * ysc)
                    lpen = QPen(alpha(col, 120), 1.0, Qt.PenStyle.DashLine)
                    p.setPen(lpen)
                    for poly in polylines(xpx, lypx, r.left(), w):
                        p.drawPolyline(poly)
        p.setClipping(False)

    def _draw_end_labels(self, p, r):
        """Direct labels at the right end of each trace, so identity never
        rests on colour alone. Collisions are resolved by pushing labels apart
        vertically."""
        store = self.view.store
        fm = QFontMetrics(self.font())
        h = fm.height()
        items = []
        for i, s in self._visible_series():
            v = store.latest(s.key)
            if v is None:
                continue
            items.append([self.y_of(v), s.label, SERIES[i % len(SERIES)]])
        if not items:
            return
        items.sort(key=lambda a: a[0])
        for j in range(1, len(items)):
            if items[j][0] - items[j - 1][0] < h:
                items[j][0] = items[j - 1][0] + h
        shift = max(0.0, items[-1][0] - r.bottom())
        for it in items:
            it[0] -= shift
        for y, label, col in items:
            y = max(r.top() + h / 2, y)
            p.setPen(QPen(alpha(QColor(col), 210), 1))
            p.drawLine(QPointF(r.right() + 2, y), QPointF(r.right() + 7, y))
            p.setPen(INK_DIM)
            p.drawText(QRectF(r.right() + 10, y - h / 2, render.RIGHT - 12, h),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter, label)

    def _legend_entries(self, fm, store, t):
        """(index, series, text, width, flag) for each series, in pane order.

        Split out from drawing so the note can be given whatever width the
        legend does not need.
        """
        out = []
        for i, s in enumerate(self.spec.series):
            # Value and limit are read at the same instant. Reading the value
            # at the crosshair but the limit at "now" compared two different
            # moments, which mattered as soon as the limits started moving.
            if t is not None:
                v = store.at(s.key, t)
                lim = store.at(s.limit, t) if s.limit else None
            else:
                v = store.latest(s.key)
                lim = store.latest(s.limit) if s.limit else None
            txt = f"{s.label} {fmt_val(v, self.spec.unit)}"
            if lim is not None and math.isfinite(lim) and lim > 0:
                txt += f"/{fmt_val(lim, self.spec.unit)}"
            flag = self._limit_flag(s, v, lim)
            if flag:
                txt += f"  {flag[0]}"
            out.append((i, s, txt, fm.horizontalAdvance(txt) + 20, flag))
        return out

    @staticmethod
    def _limit_flag(s, v, lim):
        """(text, colour) when a series is at or near its ceiling.

        The word is what carries the meaning; the colour only reinforces it.
        Both arguments must come from the same instant.
        """
        if v is None or lim is None or not s.limit or s.good_high:
            return None
        if not math.isfinite(lim) or lim <= 0:
            return None
        frac = v / lim
        if frac >= 0.98:
            return "◀ CAPPED", CRITICAL
        if frac >= 0.90:
            return "◀ near", WARNING
        return None

    def _draw_cursor(self, p, r):
        x = self.draw_cursor_rule(p, r, 110)
        if x is None:
            return
        store = self.view.store
        for i, s in self._visible_series():
            v = store.at(s.key, self.view.cursor)
            if v is None:
                continue
            y = self.y_of(v)
            if not (r.top() - 3 <= y <= r.bottom() + 3):
                continue
            # A 2px surface ring keeps overlapping markers separable.
            p.setPen(QPen(PANE_BG, 2))
            p.setBrush(QColor(SERIES[i % len(SERIES)]))
            p.drawEllipse(QPointF(x, y), 3.6, 3.6)

    # -- interaction ------------------------------------------------------
    #
    # Only the middle-button pan and the legend click are ChartPane's own;
    # everything else is TimePane's.

    def mouseMoveEvent(self, ev):
        if self.pan_from is not None:
            self.view.pan(self.pan_from - self.t_of(ev.position().x()))
            self.rangeChanged.emit()
            return
        super().mouseMoveEvent(ev)

    def leaveEvent(self, ev):
        if self.pan_from is None:
            super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.pan_from = self.t_of(ev.position().x())
            return
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.MiddleButton:
            self.pan_from = None
            return
        super().mouseReleaseEvent(ev)


class ChartLegend(Readout):
    """The right-hand end of a chart pane's header: a colour chip, the series
    name, and its value at the crosshair -- or the latest value when there is
    no crosshair. Reading values off the legend rather than off the axis is
    what makes the shared crosshair useful.

    Painted rather than laid out because it rewrites on every tick and every
    crosshair move; clicking an entry still hides that series.
    """

    def __init__(self, spec, view, on_change=lambda: None, parent=None):
        super().__init__(parent)
        self.spec, self.view = spec, view
        self.on_change = on_change
        self.setMinimumWidth(120)

    def entries(self, fm):
        """(index, series, text, width, flag) in pane order."""
        store, t = self.view.store, self.view.cursor
        out = []
        for i, s in enumerate(self.spec.series):
            # Value and limit are read at the same instant. Reading the value
            # at the crosshair but the limit at "now" compared two different
            # moments, which mattered as soon as the limits started moving.
            if t is not None:
                v = store.at(s.key, t)
                lim = store.at(s.limit, t) if s.limit else None
            else:
                v = store.latest(s.key)
                lim = store.latest(s.limit) if s.limit else None
            txt = f"{s.label} {fmt_val(v, self.spec.unit)}"
            if lim is not None and math.isfinite(lim) and lim > 0:
                txt += f"/{fmt_val(lim, self.spec.unit)}"
            flag = ChartPane._limit_flag(s, v, lim)
            if flag:
                txt += f"  {flag[0]}"
            out.append((i, s, txt, fm.horizontalAdvance(txt) + 20, flag))
        return out

    def sizeHint(self):
        """Sized for the widest text an entry can hold, not for the values
        showing right now -- a hint that moved with the data would relayout
        the header on every tick, and would also let a legend that fitted at
        startup stop fitting later."""
        fm = QFontMetrics(self.font())
        w = 0
        for s in self.spec.series:
            txt = f"{s.label} 000.0"
            if s.limit:
                txt += "/000.0"
            if s.limit and not s.good_high:
                txt += "  ◀ CAPPED"
            w += fm.horizontalAdvance(txt) + 20
        return QSize(w, render.HEADER_H)

    def paintEvent(self, _ev):
        p = QPainter(self)
        fm = QFontMetrics(self.font())
        h = self.height()
        x = self.width()
        for i, s, txt, w, flag in reversed(self.entries(fm)):
            if x - w < 0:
                s.hit = None
                continue
            x -= w
            col = QColor(SERIES[i % len(SERIES)])
            if not s.visible:
                col = alpha(col, 70)
            p.setBrush(col)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(x, h / 2 - 3.5, 7, 7))
            p.setPen(INK_DIM if s.visible else MUTED)
            p.drawText(QRectF(x + 11, 0, w - 11, h),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter, txt)
            if flag:
                p.setPen(flag[1])
                fw = fm.horizontalAdvance(txt)
                p.drawText(QRectF(x + 11 + fw - fm.horizontalAdvance(flag[0]),
                                  0, fm.horizontalAdvance(flag[0]) + 2, h),
                           Qt.AlignmentFlag.AlignLeft
                           | Qt.AlignmentFlag.AlignVCenter, flag[0])
            s.hit = (x, x + w)
        p.end()

    def mousePressEvent(self, ev):
        """Clicking an entry hides or shows that series. Colour is bound to the
        slot, not to the rank, so hiding one does not repaint the others."""
        x = ev.position().x()
        for s in self.spec.series:
            hit = getattr(s, "hit", None)
            if hit and hit[0] <= x <= hit[1]:
                s.visible = not s.visible
                self.update()
                self.on_change()
                return


def chart_frame(spec, view, indent=0):
    """A chart pane and the header that describes it."""
    body = ChartPane(spec, view)
    title = f"{spec.title}  ({spec.unit})" if spec.unit else spec.title
    legend = ChartLegend(spec, view, on_change=body.update)
    return PaneFrame(body, title, note=spec.note, readout=legend,
                     height=spec.height, indent=indent)
