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
from PyQt6.QtGui import (QFont, QFontMetrics, QImage,         # noqa: E402
                         QMouseEvent, QWheelEvent)

from amdgraph import render                                   # noqa: E402
from amdgraph.chart import ChartPane                          # noqa: E402
from amdgraph.fields import N_CORES, THROTTLE_BITS            # noqa: E402
from amdgraph.panes import (CAP_RATES, HEAT_MODES,             # noqa: E402
                            PANES)
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


def render_pane(w, h=None):
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


class TestGutters:
    """The gutters were fixed pixel counts tuned against one font size, so on a
    desktop with a larger default font the row labels lost their first
    character ("PROCHOT CPU" -> "ROCHOT CPU") and the end-of-line labels lost
    their last ("amdgpu hwmon" -> "amdgpu hwmor"). Only visible in a
    screenshot, which is a bad place to find out."""

    @pytest.fixture(autouse=True)
    def restore(self):
        before = (render.LEFT, render.RIGHT)
        yield
        render.LEFT, render.RIGHT = before

    def rows_and_series(self):
        return ([n for _b, n, _f in THROTTLE_BITS]
                + [f"core {i}" for i in range(N_CORES)],
                [s.label for spec in PANES for s in spec.series])

    @pytest.mark.parametrize("pt", [6.0, 7.5, 9.0, 11.0, 14.0, 20.0])
    def test_every_label_fits_at_any_font_size(self, pt):
        rows, series = self.rows_and_series()
        f = QFont()
        f.setPointSizeF(pt)
        render.calibrate(f, rows, series)
        fm = QFontMetrics(f)
        # The gutters the panes actually draw into, from rasters.py/chart.py.
        assert max(fm.horizontalAdvance(s) for s in rows) <= render.LEFT - 8
        assert max(fm.horizontalAdvance(s)
                   for s in series) <= render.RIGHT - 12

    def test_never_narrows_below_the_defaults(self):
        rows, series = self.rows_and_series()
        f = QFont()
        f.setPointSizeF(4.0)
        left, right = render.calibrate(f, rows, series)
        assert (left, right) >= (render._DEFAULT_LEFT, render._DEFAULT_RIGHT)

    def test_panes_and_axis_agree_after_recalibration(self, view):
        rows, series = self.rows_and_series()
        f = QFont()
        f.setPointSizeF(18.0)
        render.calibrate(f, rows, series)
        pane = ChartPane(PANES[0], view)
        render_pane(pane, PANES[0].height)
        strip = ThrottlePane(view)
        render_pane(strip)
        assert pane.plot_rect().left() == strip.plot_rect().left()
        assert pane.plot_rect().right() == strip.plot_rect().right()


class TestRendering:
    @pytest.mark.parametrize("spec", PANES, ids=lambda s: s.title)
    def test_every_pane_in_the_catalogue_paints(self, view, spec):
        render_pane(ChartPane(spec, view), spec.height)

    def test_throttle_strip_paints(self, view):
        render_pane(ThrottlePane(view))

    @pytest.mark.parametrize("mode", range(len(HEAT_MODES)),
                             ids=[m[1] for m in HEAT_MODES])
    def test_core_strip_paints_in_every_mode(self, view, mode):
        c = CorePane(view)
        c.set_mode(mode)
        render_pane(c)

    @pytest.mark.parametrize("kind", KINDS)
    def test_panes_paint_over_an_empty_store(self, kind):
        v = View(Store())
        v.update_range()
        render_pane(make(kind, v))

    @pytest.mark.parametrize("kind", KINDS)
    def test_panes_paint_with_cursor_markers_and_overlay(self, kind, view,
                                                         store):
        view.cursor = (view.t0 + view.t1) / 2
        view.markers = [(view.t0 + 10, "flipped"), (view.t1, "")]
        view.overlay = store
        w = make(kind, view)
        w.label_markers = True
        render_pane(w)

    def test_a_cursor_outside_the_window_is_not_drawn(self, view):
        view.cursor = view.t1 + 10_000
        render_pane(ChartPane(PANES[0], view), PANES[0].height)

    def test_whole_recording_exercises_the_decimation_path(self, view):
        view.window = 0.0
        view.update_range()
        render_pane(ChartPane(PANES[0], view), PANES[0].height)

    @pytest.mark.parametrize("spec", PANES, ids=lambda s: s.title)
    def test_height_is_fixed_so_the_column_lines_up(self, view, spec):
        p = ChartPane(spec, view)
        assert p.minimumHeight() == spec.height == p.maximumHeight()


class TestPaneOwnedSettings:
    """Both raster panes carry a setting that governs only themselves. Neither
    has a toolbar widget any more, so the header shows the state and a menu on
    the pane changes it -- which makes these the only route to either."""

    @staticmethod
    def open_menu(monkeypatch, widget, method):
        """Capture the menu instead of running a modal exec()."""
        from PyQt6.QtWidgets import QMenu
        seen = {}

        def fake_exec(self, *a, **k):
            seen["actions"] = [(a.text(), a.isChecked(), a.isEnabled())
                               for a in self.actions()]
            seen["menu"] = self
            return None

        monkeypatch.setattr(QMenu, "exec", fake_exec)
        method()
        return seen

    def test_core_menu_lists_every_mode_and_ticks_the_current_one(
            self, view, monkeypatch):
        c = CorePane(view)
        c.set_mode(2)
        seen = self.open_menu(monkeypatch, c, lambda: c._menu(QPoint(0, 0)))
        labels = [t for t, _chk, en in seen["actions"] if en and t]
        assert labels == [f"{n} ({u})" for _k, n, u, _l, _h in HEAT_MODES]
        checked = [t for t, chk, en in seen["actions"] if chk]
        name, unit = HEAT_MODES[2][1], HEAT_MODES[2][2]
        assert checked == [f"{name} ({unit})"]

    def test_choosing_a_mode_changes_the_pane(self, view, monkeypatch):
        c = CorePane(view)
        seen = self.open_menu(monkeypatch, c, lambda: c._menu(QPoint(0, 0)))
        target = [a for a in seen["menu"].actions()
                  if a.text() == f"{HEAT_MODES[3][1]} ({HEAT_MODES[3][2]})"]
        target[0].trigger()
        assert c.mode == 3

    def test_throttle_menu_ticks_the_current_rate(self, view, monkeypatch):
        t = ThrottlePane(view)
        t.cap_hz = CAP_RATES[1][0]
        seen = self.open_menu(monkeypatch, t, lambda: t._menu(QPoint(0, 0)))
        assert [lbl for lbl, chk, _en in seen["actions"]
                if chk] == [CAP_RATES[1][1]]

    @pytest.mark.parametrize("kind", ["throttle", "core"])
    def test_a_header_click_opens_the_menu(self, kind, view, monkeypatch):
        w = make(kind, view)
        opened = []
        monkeypatch.setattr(type(w), "_menu",
                            lambda self, at: opened.append(at))
        press(w, 300, y=6)
        release(w, 300, y=6)
        assert opened, "clicking the header should offer the setting"

    @pytest.mark.parametrize("kind", ["throttle", "core"])
    def test_a_click_in_the_plot_area_does_not(self, kind, view, monkeypatch):
        w = make(kind, view)
        opened = []
        monkeypatch.setattr(type(w), "_menu",
                            lambda self, at: opened.append(at))
        press(w, 300, y=TOP + 30)
        release(w, 300, y=TOP + 30)
        assert not opened

    @pytest.mark.parametrize("kind", ["throttle", "core"])
    def test_dragging_from_the_header_still_zooms(self, kind, view,
                                                  monkeypatch):
        """The header is a click target, not a dead zone."""
        w = make(kind, view)
        monkeypatch.setattr(type(w), "_menu", lambda self, at: None)
        t_a, t_b = w.t_of(300), w.t_of(800)
        press(w, 300, y=6)
        move(w, 800, y=6)
        release(w, 800, y=6)
        assert view.t0 == pytest.approx(t_a)
        assert view.t1 == pytest.approx(t_b)


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
        render_pane(cp, spec.height)          # populates the legend hit boxes
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
