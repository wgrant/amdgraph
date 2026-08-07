"""Layer 5 -- the pane base class.

Every widget in the scrolling column projects the same time window onto the
same x range and answers the same gestures. That used to be copied three
times, which is how the drag-selection band ended up drawn two different ways;
it lives here once instead.

Subclasses supply `plot_rect()` and `paintEvent()`, and may override
`on_click()` to do something with a left click that turned out not to be a
drag.

May import: palette, render, view (by duck typing -- a View is passed in).
"""

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from . import render
from .palette import INK, PANE_BG, SERIES, alpha
from .render import pane_font


class TimePane(QWidget):
    """Shared time projection and interaction for everything on the axis."""

    cursorMoved = pyqtSignal(object)      # float time, or None
    rangeChanged = pyqtSignal()

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.setMouseTracking(True)
        self.drag_from = None
        self.drag_to = None
        self.label_markers = False      # only the topmost pane titles them
        self.indent = 0
        self._rect = None
        self.setFont(pane_font())

    def fix_height(self, h):
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)

    # -- geometry ---------------------------------------------------------

    def set_indent(self, px):
        """The frame has been shifted right by `px`; give it back.

        Every pane shares one time axis, so an indented pane whose plot moved
        with it would no longer line up with the ruler or with its neighbours.
        Narrowing the left gutter by the indent keeps the plot area at the same
        place on screen whatever the frame does.
        """
        self.indent = px
        self._rect = None

    def gutter_left(self):
        return max(10, render.LEFT - self.indent)

    def plot_rect(self):
        raise NotImplementedError

    def x_of(self, t):
        r = self.plot_rect()
        span = max(1e-9, self.view.t1 - self.view.t0)
        return r.left() + (np.asarray(t) - self.view.t0) / span * r.width()

    def t_of(self, x):
        r = self.plot_rect()
        return (self.view.t0
                + (x - r.left()) / max(1.0, r.width())
                * (self.view.t1 - self.view.t0))

    # -- shared painting --------------------------------------------------

    def draw_cursor_rule(self, p, r, a=150):
        """The crosshair's vertical line. Chart panes draw their own dots on
        top of it and use a fainter rule so the dots stay the emphasis."""
        if self.view.cursor is None:
            return None
        x = float(self.x_of(self.view.cursor))
        if not (r.left() <= x <= r.right()):
            return None
        p.setPen(QPen(alpha(INK, a), 1))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        return x

    def draw_selection(self, p, r):
        """The drag-to-zoom band."""
        if self.drag_from is None or self.drag_to is None:
            return
        x0, x1 = sorted((float(self.x_of(self.drag_from)),
                         float(self.x_of(self.drag_to))))
        band = QRectF(max(x0, r.left()), r.top(),
                      min(x1, r.right()) - max(x0, r.left()), r.height())
        p.fillRect(band, alpha(QColor(SERIES[0]), 40))
        p.setPen(QPen(alpha(QColor(SERIES[0]), 150), 1))
        p.drawRect(band)

    def blit_rows(self, p, r, img, rowh):
        """Draw a rows x width RGBA raster into `r`, with hairline separators.

        Used by both strip charts. The buffer is kept on the widget because
        QImage wraps it without copying; hairlines rather than a gap because a
        2 px gap eats a row this short.
        """
        rows, w = img.shape[0], img.shape[1]
        self._buf = np.ascontiguousarray(img)          # keep alive for Qt
        qimg = QImage(self._buf.data, w, rows, w * 4,
                      QImage.Format.Format_ARGB32)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        p.drawImage(r, qimg)
        p.setPen(QPen(PANE_BG, 1))
        for i in range(1, rows):
            y = r.top() + i * rowh
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))

    # -- interaction ------------------------------------------------------

    def mouseMoveEvent(self, ev):
        """Track the crosshair over the plot; clear it everywhere else.

        The gutters are not part of the time axis. Reading a value there means
        asking the store for a time outside the plotted range, which correctly
        answers None -- so every readout dropped to "--" the moment the pointer
        crossed into the axis labels, and the fix looked like the values had
        stopped working rather than like the cursor had left the data.

        A drag is exempt: once a selection is under way the pointer is expected
        to wander, and losing the crosshair mid-drag would be worse.
        """
        t = self.t_of(ev.position().x())
        if self.drag_from is not None:
            self.drag_to = t
            self.cursorMoved.emit(t)
            return
        self.cursorMoved.emit(
            t if self.plot_rect().contains(ev.position()) else None)

    def leaveEvent(self, _ev):
        if self.drag_from is None:
            self.cursorMoved.emit(None)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.drag_from = self.drag_to = self.t_of(ev.position().x())

    def mouseReleaseEvent(self, ev):
        if (ev.button() != Qt.MouseButton.LeftButton
                or self.drag_from is None):
            return
        t = self.t_of(ev.position().x())
        if abs(t - self.drag_from) > 1.5:
            self.view.zoom_to(*sorted((self.drag_from, t)))
            self.rangeChanged.emit()
        else:
            self.on_click(ev.position().x(), ev.position().y())
        self.drag_from = self.drag_to = None
        self.update()

    def on_click(self, x, y):
        """A left press and release that was not a drag. Only ChartPane has
        anything to do with one; the strip charts have nothing to click."""

    def wheelEvent(self, ev):
        """Zoom only over the plot itself; anywhere else scrolls the column.

        Every pane used to swallow the wheel wherever the pointer was, which
        meant the wheel could not scroll the pane column at all -- and the
        column is over two screens tall, so that left the scrollbar as the only
        way down. Over the axis gutter, the header or the end labels the event
        is now ignored, which passes it to the scroll area.
        """
        if not self.plot_rect().contains(ev.position()):
            ev.ignore()
            return
        d = ev.angleDelta().y()
        if d:
            self.view.zoom_at(self.t_of(ev.position().x()),
                              0.8 if d > 0 else 1.25)
            self.rangeChanged.emit()
        ev.accept()
