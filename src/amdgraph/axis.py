"""Layer 4 -- the shared time ruler.

Not a TimePane: it is pinned outside the scroll area and answers no gestures,
but it must land its ticks on the same pixels the panes put their gridlines on.

May import: palette, render.
"""

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from .palette import AXIS, INK, MUTED, SURFACE, alpha
from .render import LEFT, RIGHT, fmt_time, time_ticks


class TimeAxis(QWidget):
    """Pinned below the scroll area rather than repeated per pane. Uses the
    same LEFT/RIGHT gutters, so its ticks land on the panes' vertical
    gridlines however far the pane column is scrolled."""

    def __init__(self, view, scroll, parent=None):
        super().__init__(parent)
        self.view = view
        self.scroll = scroll
        self.setFixedHeight(22)
        f = QFont()
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.5))
        self.setFont(f)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), SURFACE)
        # The panes live inside a scroll area, so their usable width is the
        # viewport's, not the window's. Without this inset the ticks drift
        # away from the gridlines the moment a scrollbar appears.
        sb = self.scroll.verticalScrollBar()
        inset = sb.width() if sb.isVisible() else 0
        w = max(10, self.width() - LEFT - RIGHT - inset)
        span = max(1e-9, self.view.t1 - self.view.t0)
        fm = QFontMetrics(self.font())
        p.setPen(QPen(AXIS, 1))
        p.drawLine(QPointF(LEFT, 0), QPointF(LEFT + w, 0))
        for t in time_ticks(self.view.t0, self.view.t1):
            x = LEFT + (t - self.view.t0) / span * w
            p.setPen(QPen(AXIS, 1))
            p.drawLine(QPointF(x, 0), QPointF(x, 4))
            p.setPen(MUTED)
            lbl = fmt_time(t)
            p.drawText(QRectF(x - 40, 4, 80, fm.height()),
                       Qt.AlignmentFlag.AlignHCenter, lbl)
        if self.view.cursor is not None:
            x = LEFT + (self.view.cursor - self.view.t0) / span * w
            if LEFT <= x <= LEFT + w:
                lbl = fmt_time(self.view.cursor)
                tw = fm.horizontalAdvance(lbl) + 10
                p.fillRect(QRectF(x - tw / 2, 2, tw, fm.height() + 2),
                           alpha(INK, 40))
                p.setPen(INK)
                p.drawText(QRectF(x - tw / 2, 3, tw, fm.height()),
                           Qt.AlignmentFlag.AlignHCenter, lbl)
        p.end()
