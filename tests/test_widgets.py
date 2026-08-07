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

from PyQt6.QtWidgets import QComboBox                         # noqa: E402

from amdgraph import render                                   # noqa: E402
from amdgraph.chart import ChartPane, chart_frame             # noqa: E402
from amdgraph.fields import N_CORES, THROTTLE_BITS            # noqa: E402
from amdgraph.panes import (CAP_DEFAULT, CAP_RATES,            # noqa: E402
                            HEAT_MODES, PANES)
from amdgraph.rasters import (CorePane, ThrottlePane,          # noqa: E402
                              core_frame, throttle_frame)
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


def wheel(w, x, dy, y=None):
    y = (w.plot_rect().top() + w.plot_rect().bottom()) / 2 if y is None else y
    ev = QWheelEvent(
        QPointF(x, y), QPointF(x, y), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False)
    w.wheelEvent(ev)
    return ev


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

    @pytest.mark.parametrize("pt", [6.0, 7.5, 9.0, 11.0, 14.0, 20.0])
    def test_the_outermost_tick_labels_fit_inside_the_body(self, view, pt):
        """Tick labels are centred on their gridline and the outermost two sit
        on the plot's own edges, so the body needs half a line of clearance at
        each end. It had 2 px at the top after the header moved out, which cut
        the top label in half at every font size."""
        rows, series = self.rows_and_series()
        f = QFont()
        f.setPointSizeF(pt)
        render.calibrate(f, rows, series)
        fm = QFontMetrics(f)
        spec = PANES[0]
        body = ChartPane(spec, view)
        body.resize(W, spec.height - render.HEADER_H)
        r = body.plot_rect()
        assert r.top() - fm.height() / 2 >= 0, "top tick label is clipped"
        assert r.bottom() + fm.height() / 2 <= body.height(), \
            "bottom tick label is clipped"

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
    def test_the_frame_owns_the_row_height(self, view, spec):
        """spec.height is the whole row -- header plus body -- so the fold
        arithmetic and the concertina measurements stay valid now that the
        header is a separate widget."""
        f = chart_frame(spec, view)
        assert f.minimumHeight() == spec.height == f.maximumHeight()
        assert f.body.height() == spec.height - render.HEADER_H


class TestHeaderLayout:
    """The header is a layout now, so the panes compete for its width. The
    first version let the note win, which silently dropped legend entries off
    the end -- a whole series vanishing with nothing to say it had."""

    @pytest.mark.parametrize("spec", PANES, ids=lambda s: s.title)
    def test_no_legend_entry_is_dropped(self, view, spec):
        for s in spec.series:
            s.visible = True
            s.hit = None
        frame = chart_frame(spec, view)
        frame.resize(1180, spec.height)
        frame.show()
        frame.readout.render(
            QImage(frame.readout.size(), QImage.Format.Format_ARGB32))
        missing = [s.label for s in spec.series if s.hit is None]
        assert not missing, f"dropped {missing} from {spec.title}"

    @pytest.mark.parametrize("spec", PANES, ids=lambda s: s.title)
    def test_the_legend_hint_does_not_move_with_the_data(self, view, spec):
        """A hint that tracked the current values would relayout the header on
        every tick, and would let a legend that fitted at startup stop fitting
        once a number grew a digit."""
        frame = chart_frame(spec, view)
        before = frame.readout.sizeHint().width()
        for i in range(30):
            view.store.append(1000.0 + i, {s.key: 987.654 for s in spec.series})
        assert frame.readout.sizeHint().width() == before

    def test_per_core_values_sit_on_their_rows_not_in_the_header(self, view,
                                                                 store):
        """Eight numbers crammed into one header strip only ever fitted four
        and a half of them, and put each one nowhere near the core it
        described. They belong at the end of their own row, the way a chart
        pane labels the end of each trace."""
        frame = core_frame(view)
        assert frame.readout is None
        body = frame.body
        body.resize(W, body.minimumHeight())
        r = body.plot_rect()
        # A gutter wide enough for the widest value, on every row.
        fm = QFontMetrics(body.font())
        widest = max(fm.horizontalAdvance(f"{v:.0f}") for v in (9999, 100.5))
        assert body.width() - r.right() - 12 >= widest
        assert r.bottom() - r.top() == N_CORES * body.ROW

    def test_a_readout_with_no_note_beside_it_takes_the_slack(self, view):
        """ThrottleReadout has no sizeHint, so a stretch spacer beside it left
        it pinned at its 160 px minimum and the active-reason list was cut
        off."""
        frame = throttle_frame(view)
        frame.resize(1180, frame.height())
        frame.show()
        assert frame.note is None
        assert frame.readout.width() > 400

    def test_the_note_yields_before_the_legend_does(self, view):
        """Something has to give on a narrow window. The note is the least
        important thing in the row, so it must be spent down to nothing before
        the legend loses a single pixel -- the legend is live data."""
        spec = next(s for s in PANES if s.note)
        frame = chart_frame(spec, view)
        frame.show()
        want = frame.readout.sizeHint().width()
        natural = QFontMetrics(frame.note.font()).horizontalAdvance(spec.note)

        # Wide: both fit.
        frame.resize(1400, spec.height)
        assert frame.readout.width() >= want
        assert frame.note.width() >= natural

        # Narrow until the legend is first squeezed, and check the note is
        # already spent by then.
        for w in range(1400, 200, -20):
            frame.resize(w, spec.height)
            if frame.readout.width() < want:
                assert frame.note.width() <= 8, (
                    f"note still {frame.note.width()} px wide while the "
                    f"legend is being cut at window width {w}")
                return
        pytest.fail("the legend was never squeezed; test proves nothing")


class TestPaneOwnedSettings:
    """Both raster panes carry a setting that governs only themselves. Each is
    now a visible combo in that pane's own header rather than a context menu
    nobody would find, which was the point of giving panes real chrome."""

    def test_the_cap_rate_is_a_visible_control(self, view):
        frame = throttle_frame(view)
        assert frame.rates.count() == len(CAP_RATES)
        assert frame.rates.currentText() == CAP_RATES[CAP_DEFAULT][1]

    def test_choosing_a_rate_reaches_the_body(self, view):
        frame = throttle_frame(view)
        seen = []
        frame.body.capRateChanged.connect(seen.append)
        frame.rates.setCurrentIndex(0)
        assert frame.body.cap_hz == CAP_RATES[0][0]
        assert seen == [CAP_RATES[0][0]]

    def test_the_core_metric_is_a_visible_control(self, view):
        frame = core_frame(view)
        assert [frame.modes.itemText(i) for i in range(frame.modes.count())] \
            == [f"{n} ({u})" for _k, n, u, _l, _h in HEAT_MODES]

    def test_choosing_a_metric_changes_the_body(self, view):
        frame = core_frame(view)
        frame.modes.setCurrentIndex(3)
        assert frame.body.mode == 3

    def test_the_metric_is_named_once_not_twice(self, view):
        """The combo states the metric and its unit; a title repeating them
        would say the same thing twice in one row."""
        frame = core_frame(view)
        assert frame.title.text() == "Per-core"
        assert frame.modes.currentText() == \
            f"{HEAT_MODES[0][1]} ({HEAT_MODES[0][2]})"

    @pytest.mark.parametrize("build", [throttle_frame, core_frame],
                             ids=["throttle", "core"])
    def test_the_control_sits_against_the_title(self, view, build):
        """It qualifies what the pane is, so it belongs next to the words it
        modifies rather than out by the readout at the far end."""
        frame = build(view)
        row = frame.header.layout()
        order = [row.itemAt(i).widget() for i in range(row.count())]
        combo = next(w for w in order if isinstance(w, QComboBox))
        assert order.index(combo) == order.index(frame.title) + 1

    def test_the_controls_do_not_take_focus(self, view):
        """A focused combo eats Space and the arrow keys; Space is the only
        way to freeze."""
        for frame in (throttle_frame(view), core_frame(view)):
            for c in frame.header.findChildren(QComboBox):
                assert c.focusPolicy() == Qt.FocusPolicy.NoFocus


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

    @pytest.mark.parametrize("kind", KINDS)
    def test_the_wheel_only_zooms_over_the_plot(self, kind, view):
        """Outside the plot the event must be ignored, so the scroll area gets
        it. The column is over two screens tall; if every pane swallows the
        wheel there is no way to scroll but the scrollbar."""
        w = make(kind, view)
        r = w.plot_rect()
        before = (view.t0, view.t1)
        for x, y, where in ((r.left() / 2, r.center().y(), "axis gutter"),
                            (r.center().x(), r.bottom() + 4, "below the plot"),
                            (r.right() + 20, r.center().y(), "end labels")):
            ev = wheel(w, x, 120, y=y)
            assert not ev.isAccepted(), f"wheel over the {where} was eaten"
            assert (view.t0, view.t1) == before, where

    @pytest.mark.parametrize("kind", KINDS)
    def test_the_wheel_over_the_plot_is_taken(self, kind, view):
        w = make(kind, view)
        ev = wheel(w, w.plot_rect().center().x(), 120)
        assert ev.isAccepted()
        assert view.t1 - view.t0 < 300.0

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
    """The legend is a painted readout inside a real header widget: painted
    because it rewrites on every tick and every crosshair move, but still the
    thing you click to hide a series."""

    @pytest.fixture
    def legend(self, view):
        spec = PANES[0]
        for s in spec.series:
            s.visible = True
        frame = chart_frame(spec, view)
        frame.resize(W, spec.height)
        # Lay the frame out for real, then paint, so the hit boxes match the
        # width the readout actually got.
        frame.show()
        frame.readout.render(
            QImage(frame.readout.size(), QImage.Format.Format_ARGB32))
        yield frame, spec
        for s in spec.series:
            s.visible = True             # PANES is module state; put it back

    def test_click_toggles_only_that_series(self, legend):
        frame, spec = legend
        hit = spec.series[0].hit
        assert hit is not None
        x = (hit[0] + hit[1]) / 2
        press(frame.readout, x, y=10)
        assert [s.visible for s in spec.series] == \
            [False] + [True] * (len(spec.series) - 1)
        press(frame.readout, x, y=10)
        assert all(s.visible for s in spec.series)

    def test_a_click_off_any_entry_toggles_nothing(self, legend):
        frame, spec = legend
        hits = [s.hit for s in spec.series if s.hit]
        gap = min(h[0] for h in hits) - 2      # left of every entry drawn
        if gap < 0:
            pytest.skip("legend fills its width; no empty space to click")
        press(frame.readout, gap, y=10)
        assert all(s.visible for s in spec.series)

    def test_hidden_series_keeps_its_colour_slot(self, legend):
        """Colour is bound to position, not rank, so hiding one series must not
        repaint the others."""
        frame, spec = legend
        body = frame.body
        assert [i for i, _ in body._visible_series()] == \
            list(range(len(spec.series)))
        spec.series[0].visible = False
        assert [i for i, _ in body._visible_series()] == \
            list(range(1, len(spec.series)))      # not renumbered
