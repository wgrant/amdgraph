"""Layer 5 -- the pane frame: native chrome around a painted body.

A pane is a header row of real widgets over one custom-painted body. The header
is chrome -- a title, a note, sometimes a control -- and chrome is what widgets
are for: layout handles eliding, the control is a real combo that can be seen
and tabbed to instead of a context menu nobody discovers, and the text is text
rather than a drawText call.

Two things stay painted, for the same reason the charts do:

  the body   grid, traces, cursor, and the axis gutters. Splitting the gutter
             into its own widget would mean giving it the y-scale, which is
             computed during the body's own fit -- more coupling than it saves.

  the readout  the live values at the crosshair. Four series across seventeen
             panes, rewritten at ~30 Hz while the pointer sweeps, is around
             seventy QLabel updates a frame, each triggering layout. As one
             painted strip it is a single drawText loop.

May import: palette, render.
"""

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy,
                             QVBoxLayout, QWidget)

from . import render
from .palette import MUTED, PANE_BG
from .render import HEADER_H, pane_font


class ElidedLabel(QLabel):
    """A label that gives up its width rather than forcing the row wider.

    The note is the least important thing in a header and should be the first
    thing to shrink -- but a plain QLabel refuses to go below the width of its
    text, which squeezed the legend beside it until entries fell off the end.
    Ignored size policy lets the layout take the space back; the text elides to
    whatever is left.
    """

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, _ev):
        p = QPainter(self)
        fm = QFontMetrics(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.drawText(QRectF(self.rect()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(self._full, Qt.TextElideMode.ElideRight,
                                 self.width()))
        p.end()


class Readout(QWidget):
    """The live half of a header, painted.

    Subclasses implement draw(painter, rect); the frame calls update() on each
    tick and each crosshair move.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(pane_font())
        # Minimum, not Preferred: the layout may grow a readout but must never
        # shrink it below what it asked for, or entries silently fall off the
        # end of it -- which is exactly what the note did to the legend.
        self.setSizePolicy(QSizePolicy.Policy.Minimum,
                           QSizePolicy.Policy.Preferred)

    def draw(self, p, r):
        raise NotImplementedError

    def paintEvent(self, _ev):
        p = QPainter(self)
        self.draw(p, QRectF(self.rect()))
        p.end()


class PaneFrame(QWidget):
    """One row of the column: header widgets above a painted body.

    `indent` shifts the whole frame right -- for showing that a group contains
    its panes -- and the body compensates by narrowing its own left gutter by
    the same amount, so the plot area stays at a fixed position on screen. The
    panes all share one time axis; if an indented pane's gridlines moved, the
    ruler at the bottom would stop describing it.
    """

    def __init__(self, body, title, note=None, controls=(), readout=None,
                 height=None, indent=0, parent=None):
        super().__init__(parent)
        self.body = body
        self.readout = readout
        self.spec = getattr(body, "spec", None)
        self._indent = indent
        body.set_indent(indent)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(indent, 0, 0, 0)
        lay.setSpacing(0)

        self.header = QWidget()
        self.header.setFixedHeight(HEADER_H)
        h = QHBoxLayout(self.header)
        h.setContentsMargins(6, 0, 8, 0)
        h.setSpacing(8)

        f = QFont(pane_font())
        f.setBold(True)
        self.title = QLabel(title)
        self.title.setFont(f)
        h.addWidget(self.title)

        if note:
            # Elides, and yields its width to the legend rather than the other
            # way round. It used to be drawn into a fixed 320 px box and cut
            # off mid-word.
            self.note = ElidedLabel(note)
            self.note.setFont(pane_font())
            self.note.setStyleSheet(f"color:{MUTED.name()};")
            h.addWidget(self.note, 1)
        else:
            self.note = None
            h.addStretch(1)

        for c in controls:
            c.setFont(pane_font())
            c.setFixedHeight(HEADER_H - 6)
            h.addWidget(c)

        if readout is not None:
            h.addWidget(readout, 0)

        lay.addWidget(self.header)
        lay.addWidget(body, 1)

        if height is not None:
            self.setFixedHeight(height)
            body.setFixedHeight(height - HEADER_H)

    # -- what the window drives -------------------------------------------

    @property
    def label_markers(self):
        return self.body.label_markers

    @label_markers.setter
    def label_markers(self, on):
        self.body.label_markers = on

    def update_live(self):
        """Repaint the parts that change with the data or the crosshair."""
        self.body.update()
        if self.readout is not None:
            self.readout.update()

    def paintEvent(self, _ev):
        # The header sits on the pane's own background, not the window's, so a
        # pane reads as one object rather than a strip floating above a chart.
        p = QPainter(self)
        p.fillRect(self.rect(), PANE_BG)
        p.end()


def elide(fm, text, width):
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, max(0, int(width)))


def readout_metrics(widget):
    return QFontMetrics(widget.font())


def right_edge_gutter():
    """Readouts stop where the body's right gutter starts, so the numbers line
    up over the end-of-line labels they correspond to."""
    return render.RIGHT
