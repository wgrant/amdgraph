"""Layer 4 -- the shared time ruler.

Not a TimePane: it is pinned outside the scroll area and answers no gestures,
but it must land its ticks on the same pixels the panes put their gridlines on.

May import: palette, render.
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from . import render
from .palette import AXIS, INK, MUTED, SURFACE, alpha
from .render import fmt_time, pane_font, time_ticks


class TimeAxis(QWidget):
    """Pinned below the scroll area rather than repeated per pane. Uses the
    same LEFT/RIGHT gutters, so its ticks land on the panes' vertical
    gridlines however far the pane column is scrolled."""

    def __init__(self, view, scroll, parent=None):
        super().__init__(parent)
        self.view = view
        self.scroll = scroll
        self.setFont(pane_font())
        # 4 px of tick, then the label. 22 px held both at the smallest font
        # this program uses and clipped from about 11 pt upward.
        fm = QFontMetrics(self.font())
        self.setFixedHeight(max(22, 4 + fm.height() + 4))

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), SURFACE)
        # The panes live inside a scroll area, so their usable width is the
        # viewport's, not the window's. Without this inset the ticks drift
        # away from the gridlines the moment a scrollbar appears.
        sb = self.scroll.verticalScrollBar()
        inset = sb.width() if sb.isVisible() else 0
        left = render.LEFT
        w = max(10, self.width() - left - render.RIGHT - inset)
        span = max(1e-9, self.view.t1 - self.view.t0)
        fm = QFontMetrics(self.font())
        # Where the crosshair's own label will go, worked out before the ticks
        # so a tick can stand aside for it. Its background is translucent, so
        # overlapping text showed through as two times printed on top of each
        # other rather than as one winning.
        busy = None
        if self.view.cursor is not None:
            cx = left + (self.view.cursor - self.view.t0) / span * w
            if left <= cx <= left + w:
                cw = fm.horizontalAdvance(fmt_time(self.view.cursor)) + 10
                busy = (cx - cw / 2, cx + cw / 2)

        p.setPen(QPen(AXIS, 1))
        p.drawLine(QPointF(left, 0), QPointF(left + w, 0))
        for t in time_ticks(self.view.t0, self.view.t1):
            x = left + (t - self.view.t0) / span * w
            p.setPen(QPen(AXIS, 1))
            p.drawLine(QPointF(x, 0), QPointF(x, 4))
            lbl = fmt_time(t)
            lw = fm.horizontalAdvance(lbl) + 8
            # The tick mark itself always stays: it is the gridline's anchor,
            # and only the text would have collided.
            if busy and x - lw / 2 < busy[1] and x + lw / 2 > busy[0]:
                continue
            p.setPen(MUTED)
            p.drawText(QRectF(x - lw / 2, 4, lw, fm.height()),
                       Qt.AlignmentFlag.AlignHCenter, lbl)
        if self.view.cursor is not None:
            x = left + (self.view.cursor - self.view.t0) / span * w
            if left <= x <= left + w:
                lbl = fmt_time(self.view.cursor)
                tw = fm.horizontalAdvance(lbl) + 10
                p.fillRect(QRectF(x - tw / 2, 2, tw, fm.height() + 2),
                           alpha(INK, 40))
                p.setPen(INK)
                p.drawText(QRectF(x - tw / 2, 3, tw, fm.height()),
                           Qt.AlignmentFlag.AlignHCenter, lbl)
        p.end()
