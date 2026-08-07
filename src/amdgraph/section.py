"""Layer 5 -- the collapsible section header.

A QToolButton rather than a hand-painted widget. The first version drew its own
disclosure triangle and could not be focused, tabbed to, or toggled by
keyboard -- a custom QWidget gets none of that for free, and losing it was an
accessibility regression rather than a style choice. QToolButton is also what
Qt's own collapsible sections are built from.

It exists because the pane column is over two screens tall, so what sits above
the fold is a real decision, and some panes are worth keeping without being
worth that space.

May import: render.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QToolButton

from .render import pane_font


class SectionHeader(QToolButton):
    """One clickable strip standing in for a run of panes.

    `toggled(bool)` is QToolButton's own signal, so the caller wires it the
    same way it would any other checkable button.
    """

    def __init__(self, group, parent=None):
        super().__init__(parent)
        self.group = group
        self.setFont(pane_font())
        self.setCheckable(True)
        self.setChecked(not group.collapsed)
        self.setAutoRaise(True)
        self.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy().Expanding,
                           self.sizePolicy().verticalPolicy().Fixed)
        self.setToolTip("Show or hide: " + ", ".join(group.titles))
        self.toggled.connect(self._restyle)
        self._restyle(self.isChecked())

    @property
    def expanded(self):
        return self.isChecked()

    def set_expanded(self, on):
        self.setChecked(on)

    def _restyle(self, on):
        # Collapsed, the header still names what it is hiding: a bare
        # disclosure arrow says something is there but not whether it is worth
        # opening, and these panes were grouped precisely because you only want
        # them sometimes. Expanded, the panes speak for themselves.
        self.setArrowType(Qt.ArrowType.DownArrow if on
                          else Qt.ArrowType.RightArrow)
        self.setText(self.group.title if on or not self.group.note
                     else f"{self.group.title}   —   {self.group.note}")
