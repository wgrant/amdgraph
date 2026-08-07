"""Layer 4 -- the collapsible section header.

Not a TimePane: it carries no data and no time axis. It exists because the pane
column is about 2.4 screens tall, so what sits above the fold is a real
decision, and some panes are worth keeping without being worth that space.

May import: palette, render.
"""

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QWidget

from .palette import INK_DIM, MUTED, SURFACE, alpha
from .render import pane_font


class SectionHeader(QWidget):
    """One clickable strip standing in for a run of panes.

    Collapsed, it still names what it is hiding -- a disclosure triangle over
    a bare title tells you there is something there but not whether it is worth
    opening, and the whole reason these panes were grouped is that you only
    want them sometimes.
    """

    toggled = pyqtSignal(bool)          # True when expanded

    HEIGHT = 22

    def __init__(self, group, parent=None):
        super().__init__(parent)
        self.group = group
        self.expanded = not group.collapsed
        self.setFixedHeight(self.HEIGHT)
        self.setFont(pane_font())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Show or hide: {', '.join(group.titles)}")

    def set_expanded(self, on):
        if on != self.expanded:
            self.expanded = on
            self.toggled.emit(on)
            self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.set_expanded(not self.expanded)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), SURFACE)
        fm = QFontMetrics(self.font())

        p.setPen(INK_DIM)
        marker = "▾" if self.expanded else "▸"
        p.drawText(QRectF(8, 0, 14, self.HEIGHT),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   marker)

        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(24, 0, 220, self.HEIGHT),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.group.title)
        title_w = fm.horizontalAdvance(self.group.title) + 14
        p.setFont(self.font())

        # Only while collapsed: expanded, the panes speak for themselves and a
        # list of their own names above them is noise.
        if not self.expanded and self.group.note:
            p.setPen(MUTED)
            x = 24 + title_w
            p.drawText(QRectF(x, 0, max(0, self.width() - x - 8), self.HEIGHT),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(self.group.note,
                                     Qt.TextElideMode.ElideRight,
                                     max(0, int(self.width() - x - 8))))

        # A hairline under the header, so a collapsed section reads as a seam
        # in the column rather than as another pane.
        p.setPen(alpha(INK_DIM, 40))
        p.drawLine(8, self.HEIGHT - 1, self.width() - 8, self.HEIGHT - 1)
        p.end()
