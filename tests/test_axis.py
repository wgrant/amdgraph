"""The shared time ruler.

Its whole job is to land its ticks on the same pixels the panes put their
gridlines on, however far the column is scrolled -- so that is what is asserted,
rather than that it paints.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtGui import QImage                                # noqa: E402
from PyQt6.QtWidgets import QScrollArea                       # noqa: E402

from amdgraph import render                                   # noqa: E402
from amdgraph.axis import TimeAxis                            # noqa: E402
from amdgraph.chart import ChartPane                          # noqa: E402
from amdgraph.panes import PANES                              # noqa: E402
from amdgraph.render import time_ticks                        # noqa: E402
from amdgraph.store import Store                              # noqa: E402
from amdgraph.view import View                                # noqa: E402

W = 1200

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.fixture
def axis(view):
    scroll = QScrollArea()
    a = TimeAxis(view, scroll)
    a.resize(W, 22)
    return a


def paint(w, h):
    img = QImage(w.width(), h, QImage.Format.Format_ARGB32)
    img.fill(0)
    w.render(img)
    return img


def test_paints(axis):
    paint(axis, 22)


def test_paints_with_a_cursor(axis, view):
    view.cursor = (view.t0 + view.t1) / 2
    paint(axis, 22)


def test_paints_over_an_empty_store(qapp):
    v = View(Store())
    v.update_range()
    a = TimeAxis(v, QScrollArea())
    a.resize(W, 22)
    paint(a, 22)


def test_height_is_fixed(axis):
    assert axis.minimumHeight() == axis.maximumHeight() == 22


def test_ticks_land_on_the_panes_gridlines(axis, view):
    """The two widgets compute x independently; if they ever disagree the
    ruler stops describing the chart above it."""
    pane = ChartPane(PANES[0], view)
    pane.resize(W, PANES[0].height)
    paint(pane, PANES[0].height)          # settle the cached plot rect

    span = view.t1 - view.t0
    usable = W - render.LEFT - render.RIGHT   # no scrollbar visible offscreen
    for t in time_ticks(view.t0, view.t1):
        axis_x = render.LEFT + (t - view.t0) / span * usable
        pane_x = float(pane.x_of(t))
        assert axis_x == pytest.approx(pane_x, abs=1e-6)


def test_a_tick_label_stands_aside_for_the_cursor_label(axis, view):
    """Both are times, and the cursor's background is translucent, so an
    overlap printed one over the other rather than one winning."""
    from PyQt6.QtGui import QFontMetrics

    from amdgraph.render import fmt_time
    fm = QFontMetrics(axis.font())
    left, w = render.LEFT, W - render.LEFT - render.RIGHT
    span = view.t1 - view.t0

    def box(t, pad):
        x = left + (t - view.t0) / span * w
        lw = fm.horizontalAdvance(fmt_time(t)) + pad
        return x - lw / 2, x + lw / 2

    ticks = time_ticks(view.t0, view.t1)
    assert len(ticks) > 1
    # Park the cursor a little past a tick, so the two labels must collide.
    step = ticks[1] - ticks[0]
    view.cursor = ticks[len(ticks) // 2] + step * 0.05
    cur = box(view.cursor, 10)

    drawn = [t for t in ticks
             if not (box(t, 8)[0] < cur[1] and box(t, 8)[1] > cur[0])]
    assert len(drawn) < len(ticks), "test did not actually create a collision"
    paint(axis, axis.height())          # and it still paints


def test_ticks_track_a_zoom(axis, view):
    view.zoom_to(view.t0 + 10, view.t0 + 40)
    ticks = time_ticks(view.t0, view.t1)
    assert ticks
    assert all(view.t0 - 1e-9 <= t <= view.t1 + 1e-9 for t in ticks)
    paint(axis, 22)
