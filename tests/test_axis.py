"""The shared time ruler.

Its whole job is to land its ticks on the same pixels the panes put their
gridlines on, however far the column is scrolled -- so that is what is asserted,
rather than that it paints.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtGui import QImage                                # noqa: E402
from PyQt6.QtWidgets import QScrollArea                       # noqa: E402

from amdgraph.axis import TimeAxis                            # noqa: E402
from amdgraph.chart import ChartPane                          # noqa: E402
from amdgraph.panes import PANES                              # noqa: E402
from amdgraph.render import LEFT, RIGHT, time_ticks           # noqa: E402
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


def render(w, h):
    img = QImage(w.width(), h, QImage.Format.Format_ARGB32)
    img.fill(0)
    w.render(img)
    return img


def test_paints(axis):
    render(axis, 22)


def test_paints_with_a_cursor(axis, view):
    view.cursor = (view.t0 + view.t1) / 2
    render(axis, 22)


def test_paints_over_an_empty_store(qapp):
    v = View(Store())
    v.update_range()
    a = TimeAxis(v, QScrollArea())
    a.resize(W, 22)
    render(a, 22)


def test_height_is_fixed(axis):
    assert axis.minimumHeight() == axis.maximumHeight() == 22


def test_ticks_land_on_the_panes_gridlines(axis, view):
    """The two widgets compute x independently; if they ever disagree the
    ruler stops describing the chart above it."""
    pane = ChartPane(PANES[0], view)
    pane.resize(W, PANES[0].height)
    render(pane, PANES[0].height)          # settle the cached plot rect

    span = view.t1 - view.t0
    usable = W - LEFT - RIGHT              # no scrollbar visible offscreen
    for t in time_ticks(view.t0, view.t1):
        axis_x = LEFT + (t - view.t0) / span * usable
        pane_x = float(pane.x_of(t))
        assert axis_x == pytest.approx(pane_x, abs=1e-6)


def test_ticks_track_a_zoom(axis, view):
    view.zoom_to(view.t0 + 10, view.t0 + 40)
    ticks = time_ticks(view.t0, view.t1)
    assert ticks
    assert all(view.t0 - 1e-9 <= t <= view.t1 + 1e-9 for t in ticks)
    render(axis, 22)
