"""Layer 2 -- colour.

Dark-mode steps, validated against the #16161a chart surface: all four
categorical slots sit in the L 0.48-0.67 band, clear the 0.1 chroma floor,
hold >= 3:1 contrast, and the worst adjacent pair separates by CVD dE 8.4 /
normal-vision dE 19.8. Slots are assigned by position within a pane and never
cycled, so a series keeps its colour when other series are hidden.

May import: nothing in this package.
"""

import numpy as np
from PyQt6.QtGui import QColor

SURFACE = QColor("#16161a")
PANE_BG = QColor("#1a1a1e")
INK = QColor("#f2f2ee")
INK_DIM = QColor("#c3c2b7")
MUTED = QColor("#898781")
GRID = QColor("#2c2c2a")
AXIS = QColor("#383835")

SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500"]

# Status is reserved -- never reused as a series colour, and never carries
# meaning without an accompanying label ("near" / "CAPPED").
WARNING = QColor("#fab219")
CRITICAL = QColor("#d03b3b")

# Markers are annotations, not data and not status: magenta, the one
# categorical slot no pane uses, so they never read as a series or an alarm.
MARKER = QColor("#d55181")

# Sequential blue ramp for the per-core heat strip, ordered dark -> light so
# "near zero" recedes toward the dark surface.
RAMP = ["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6",
        "#3987e5", "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6",
        "#cde2fb"]


def build_lut():
    """256-entry BGRA lookup table interpolated along RAMP."""
    stops = np.array([[QColor(h).red(), QColor(h).green(), QColor(h).blue()]
                      for h in RAMP], dtype=np.float64)
    xs = np.linspace(0, 255, len(RAMP))
    idx = np.arange(256)
    lut = np.zeros((256, 4), dtype=np.uint8)
    for c in range(3):
        lut[:, 2 - c] = np.interp(idx, xs, stops[:, c]).astype(np.uint8)
    lut[:, 3] = 255
    return lut


LUT = build_lut()


def alpha(color, a):
    c = QColor(color)
    c.setAlpha(a)
    return c
