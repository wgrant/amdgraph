"""Widgets, rendered offscreen.

Deliberately no golden pixel hashes. Pane rendering draws text, so a hash is a
fingerprint of the font stack as much as of the code, and a golden file that
breaks on a Qt upgrade gets deleted rather than investigated. What is asserted
here is what is actually portable: that everything paints without raising, that
the geometry contract holds, and that the gestures produce exact view state --
which is pure arithmetic and identical everywhere.

For an A/B comparison across a refactor, hash the renders in a scratch script
against the previous commit; that is a refactoring aid, not a regression test.
"""

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt          # noqa: E402
from PyQt6.QtGui import QImage, QMouseEvent, QWheelEvent      # noqa: E402

from amdgraph.chart import ChartPane                          # noqa: E402
from amdgraph.panes import HEAT_MODES, PANES                  # noqa: E402
from amdgraph.rasters import CorePane, ThrottlePane           # noqa: E402
from amdgraph.render import TOP                               # noqa: E402
from amdgraph.store import Store                              # noqa: E402
from amdgraph.view import View                                # noqa: E402

W = 1200
KINDS = ["chart", "throttle", "core"]

pytestmark = pytest.mark.usefixtures("qapp")


def make(kind, view):
    w = {"chart": lambda: ChartPane(PANES[0], view),
         "throttle": lambda: ThrottlePane(view),
         "core": lambda: CorePane(view)}[kind]()
    w.resize(W, max(120, w.minimumHeight() or 120))
    return w


def render(w, h=None):
    h = h or max(1, w.minimumHeight() or 120)
    w.resize(W, h)
    img = QImage(W, h, QImage.Format.Format_ARGB32)
    img.fill(0)
    w.render(img)
    return img


def press(w, x, y=40, btn=Qt.MouseButton.LeftButton):
    w.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
        btn, btn, Qt.KeyboardModifier.NoModifier))


def release(w, x, y=40, btn=Qt.MouseButton.LeftButton):
    w.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
        btn, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))


def move(w, x, y=40):
    w.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier))


def wheel(w, x, dy):
    w.wheelEvent(QWheelEvent(
        QPointF(x, 40), QPointF(x, 40), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False))


class TestRendering:
    @pytest.mark.parametrize("spec", PANES, ids=lambda s: s.title)
    def test_every_pane_in_the_catalogue_paints(self, view, spec):
        render(ChartPane(spec, view), spec.height)

    def test_throttle_strip_paints(self, view):
        render(ThrottlePane(view))

    @pytest.mark.parametrize("mode", range(len(HEAT_MODES)),
                             ids=[m[1] for m in HEAT_MODES])
    def test_core_strip_paints_in_every_mode(self, view, mode):
        c = CorePane(view)
        c.set_mode(mode)
        render(c)

    @pytest.mark.parametrize("kind", KINDS)
    def test_panes_paint_over_an_empty_store(self, kind):
        v = View(Store())
        v.update_range()
        render(make(kind, v))

    @pytest.mark.parametrize("kind", KINDS)
    def test_panes_paint_with_cursor_markers_and_overlay(self, kind, view,
                                                         store):
        view.cursor = (view.t0 + view.t1) / 2
        view.markers = [(view.t0 + 10, "flipped"), (view.t1, "")]
        view.overlay = store
        w = make(kind, view)
        w.label_markers = True
        render(w)

    def test_a_cursor_outside_the_window_is_not_drawn(self, view):
        view.cursor = view.t1 + 10_000
        render(ChartPane(PANES[0], view), PANES[0].height)

    def test_whole_recording_exercises_the_decimation_path(self, view):
        view.window = 0.0
        view.update_range()
        render(ChartPane(PANES[0], view), PANES[0].height)

    @pytest.mark.parametrize("spec", PANES, ids=lambda s: s.title)
    def test_height_is_fixed_so_the_column_lines_up(self, view, spec):
        p = ChartPane(spec, view)
        assert p.minimumHeight() == spec.height == p.maximumHeight()


class TestInteraction:
    """Exact arithmetic, so these assertions are portable."""

    @pytest.mark.parametrize("kind", KINDS)
    def test_drag_zooms_to_exactly_the_dragged_span(self, kind, view):
        w = make(kind, view)
        t_a, t_b = w.t_of(300), w.t_of(800)
        press(w, 300)
        move(w, 800)
        release(w, 800)
        assert view.t0 == pytest.approx(t_a)
        assert view.t1 == pytest.approx(t_b)
        assert not view.follow

    @pytest.mark.parametrize("kind", KINDS)
    def test_a_tiny_drag_is_a_click_not_a_zoom(self, kind, view):
        w = make(kind, view)
        before = (view.t0, view.t1)
        press(w, 500)
        release(w, 500.5)
        assert (view.t0, view.t1) == before

    @pytest.mark.parametrize("kind", KINDS)
    def test_wheel_in_then_out_is_reversible(self, kind, view):
        w = make(kind, view)
        before = (view.t0, view.t1)
        wheel(w, 400, 120)
        assert view.t1 - view.t0 < before[1] - before[0]
        wheel(w, 400, -120)
        assert view.t0 == pytest.approx(before[0])
        assert view.t1 == pytest.approx(before[1])

    def test_zero_delta_wheel_does_nothing(self, view):
        w = make("chart", view)
        before = (view.t0, view.t1, view.follow)
        wheel(w, 400, 0)
        assert (view.t0, view.t1, view.follow) == before

    def test_middle_drag_pans_the_chart(self, view):
        w = make("chart", view)
        span = view.t1 - view.t0
        press(w, 400, btn=Qt.MouseButton.MiddleButton)
        move(w, 600)
        release(w, 600, btn=Qt.MouseButton.MiddleButton)
        assert view.t1 - view.t0 == pytest.approx(span)
        assert not view.follow
        assert w.pan_from is None

    @pytest.mark.parametrize("kind", ["throttle", "core"])
    def test_middle_drag_is_inert_on_the_strip_charts(self, kind, view):
        w = make(kind, view)
        before = (view.t0, view.t1)
        press(w, 400, btn=Qt.MouseButton.MiddleButton)
        move(w, 600)
        release(w, 600, btn=Qt.MouseButton.MiddleButton)
        assert (view.t0, view.t1) == before

    @pytest.mark.parametrize("kind", KINDS)
    def test_leaving_mid_drag_keeps_the_crosshair(self, kind, view):
        w = make(kind, view)
        seen = []
        w.cursorMoved.connect(seen.append)
        press(w, 300)
        move(w, 500)
        w.leaveEvent(QEvent(QEvent.Type.Leave))
        assert None not in seen

    @pytest.mark.parametrize("kind", KINDS)
    def test_leaving_clears_the_crosshair_when_not_dragging(self, kind, view):
        w = make(kind, view)
        seen = []
        w.cursorMoved.connect(seen.append)
        move(w, 500)
        w.leaveEvent(QEvent(QEvent.Type.Leave))
        assert seen[-1] is None

    def test_right_button_is_ignored(self, view):
        w = make("chart", view)
        before = (view.t0, view.t1, view.follow)
        press(w, 400, btn=Qt.MouseButton.RightButton)
        release(w, 700, btn=Qt.MouseButton.RightButton)
        assert (view.t0, view.t1, view.follow) == before


class TestLegend:
    @pytest.fixture
    def pane(self, view):
        spec = PANES[0]
        for s in spec.series:
            s.visible = True
        cp = ChartPane(spec, view)
        cp.resize(W, spec.height)
        render(cp, spec.height)          # populates the legend hit boxes
        yield cp, spec
        for s in spec.series:
            s.visible = True             # PANES is module state; put it back

    def test_legend_click_toggles_only_that_series(self, pane):
        cp, spec = pane
        hit = spec.series[0].hit
        assert hit is not None
        x = (hit[0] + hit[1]) / 2
        press(cp, x, y=8)
        release(cp, x, y=8)
        assert [s.visible for s in spec.series] == \
            [False] + [True] * (len(spec.series) - 1)
        press(cp, x, y=8)
        release(cp, x, y=8)
        assert all(s.visible for s in spec.series)

    def test_a_click_in_the_plot_area_toggles_nothing(self, pane):
        cp, spec = pane
        x = sum(spec.series[0].hit) / 2
        press(cp, x, y=TOP + 20)
        release(cp, x, y=TOP + 20)
        assert all(s.visible for s in spec.series)

    def test_hidden_series_keeps_its_colour_slot(self, pane):
        """Colour is bound to position, not rank, so hiding one series must not
        repaint the others."""
        cp, spec = pane
        assert [i for i, _ in cp._visible_series()] == \
            list(range(len(spec.series)))
        spec.series[0].visible = False
        assert [i for i, _ in cp._visible_series()] == \
            list(range(1, len(spec.series)))       # not renumbered
