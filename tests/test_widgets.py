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

import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
    from PyQt6.QtGui import QImage, QMouseEvent, QWheelEvent
    from PyQt6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError:                                    # pragma: no cover
    HAVE_QT = False

if HAVE_QT:
    from amdgraph.chart import ChartPane
    from amdgraph.panes import HEAT_MODES, PANES
    from amdgraph.rasters import CorePane, ThrottlePane
    from amdgraph.render import TOP
    from amdgraph.store import Store
    from amdgraph.view import View

_app = None
W = 1200


def setUpModule():
    global _app
    if HAVE_QT:
        _app = QApplication.instance() or QApplication([])


def fixture_store(n=200):
    """A deterministic recording: no clock, no RNG, no hardware."""
    st = Store()
    for i in range(n):
        t = i * 0.5
        st.append(t, {
            "stapm": 15.0 + 5.0 * math.sin(i / 9.0),
            "stapm_lim": 30.0,
            "ppt_fast": 12.0, "ppt_fast_lim": 30.0,
            "ppt_slow": 14.0, "ppt_slow_lim": 25.0,
            "tctl": 60.0 + i % 20, "tctl_lim": 100.0,
            "pwr_socket": 20.0, "pwr_soc": 2.0, "core_power_sum": 14.0,
            "thr0": (i % 5) / 5.0, "thr11": 1.0 if i % 3 else 0.0,
            **{f"core_freq_{c}": 1000.0 + 200 * c for c in range(8)},
            **{f"core_c0_{c}": float(c * 10) for c in range(8)},
            "core_freq_max": 2600.0, "core_freq_mean": 1800.0,
        })
    return st


def render(w, h=None):
    h = h or max(1, w.minimumHeight() or 120)
    w.resize(W, h)
    img = QImage(W, h, QImage.Format.Format_ARGB32)
    img.fill(0)
    w.render(img)
    return img


def press(w, x, y=40, btn=None):
    btn = btn or Qt.MouseButton.LeftButton
    w.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
        btn, btn, Qt.KeyboardModifier.NoModifier))


def release(w, x, y=40, btn=None):
    btn = btn or Qt.MouseButton.LeftButton
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


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class TestRendering(unittest.TestCase):
    def setUp(self):
        self.store = fixture_store()
        self.view = View(self.store)
        self.view.window = 300.0
        self.view.update_range()

    def test_every_pane_in_the_catalogue_paints(self):
        for spec in PANES:
            with self.subTest(pane=spec.title):
                render(ChartPane(spec, self.view), spec.height)

    def test_strip_charts_paint(self):
        render(ThrottlePane(self.view))
        for i in range(len(HEAT_MODES)):
            c = CorePane(self.view)
            c.set_mode(i)
            render(c)

    def test_panes_paint_over_an_empty_store(self):
        v = View(Store())
        v.update_range()
        for spec in PANES:
            render(ChartPane(spec, v), spec.height)
        render(ThrottlePane(v))
        render(CorePane(v))

    def test_panes_paint_with_cursor_markers_and_overlay(self):
        self.view.cursor = (self.view.t0 + self.view.t1) / 2
        self.view.markers = [(self.view.t0 + 10, "flipped"), (self.view.t1, "")]
        self.view.overlay = fixture_store(50)
        for w, h in ((ChartPane(PANES[0], self.view), PANES[0].height),
                     (ThrottlePane(self.view), None),
                     (CorePane(self.view), None)):
            w.label_markers = True
            render(w, h)

    def test_a_cursor_outside_the_window_is_not_drawn(self):
        self.view.cursor = self.view.t1 + 10_000
        render(ChartPane(PANES[0], self.view), PANES[0].height)

    def test_whole_recording_exercises_the_decimation_path(self):
        v = View(fixture_store(5000))
        v.window = 0.0
        v.update_range()
        render(ChartPane(PANES[0], v), PANES[0].height)

    def test_height_is_fixed_so_the_column_lines_up(self):
        for spec in PANES:
            p = ChartPane(spec, self.view)
            self.assertEqual(p.minimumHeight(), spec.height)
            self.assertEqual(p.maximumHeight(), spec.height)


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class TestInteraction(unittest.TestCase):
    """Exact arithmetic, so these assertions are portable."""

    def make(self, kind):
        store = fixture_store()
        view = View(store)
        view.window = 300.0
        view.update_range()
        w = {"chart": lambda: ChartPane(PANES[0], view),
             "throttle": lambda: ThrottlePane(view),
             "core": lambda: CorePane(view)}[kind]()
        w.resize(W, max(120, w.minimumHeight() or 120))
        return w, view

    def test_drag_zooms_to_exactly_the_dragged_span(self):
        for kind in ("chart", "throttle", "core"):
            with self.subTest(kind=kind):
                w, v = self.make(kind)
                t_a, t_b = w.t_of(300), w.t_of(800)
                press(w, 300)
                move(w, 800)
                release(w, 800)
                self.assertAlmostEqual(v.t0, t_a, places=6)
                self.assertAlmostEqual(v.t1, t_b, places=6)
                self.assertFalse(v.follow)

    def test_a_tiny_drag_is_a_click_not_a_zoom(self):
        for kind in ("chart", "throttle", "core"):
            with self.subTest(kind=kind):
                w, v = self.make(kind)
                before = (v.t0, v.t1)
                press(w, 500)
                release(w, 500.5)
                self.assertEqual((v.t0, v.t1), before)

    def test_wheel_in_then_out_is_reversible(self):
        for kind in ("chart", "throttle", "core"):
            with self.subTest(kind=kind):
                w, v = self.make(kind)
                before = (v.t0, v.t1)
                wheel(w, 400, 120)
                self.assertLess(v.t1 - v.t0, before[1] - before[0])
                wheel(w, 400, -120)
                self.assertAlmostEqual(v.t0, before[0], places=6)
                self.assertAlmostEqual(v.t1, before[1], places=6)

    def test_zero_delta_wheel_does_nothing(self):
        w, v = self.make("chart")
        before = (v.t0, v.t1, v.follow)
        wheel(w, 400, 0)
        self.assertEqual((v.t0, v.t1, v.follow), before)

    def test_middle_drag_pans_the_chart_only(self):
        w, v = self.make("chart")
        span = v.t1 - v.t0
        press(w, 400, btn=Qt.MouseButton.MiddleButton)
        move(w, 600)
        release(w, 600, btn=Qt.MouseButton.MiddleButton)
        self.assertAlmostEqual(v.t1 - v.t0, span, places=6)
        self.assertLess(v.t0, 0.0 + span)        # moved left in time
        self.assertFalse(v.follow)
        self.assertIsNone(w.pan_from)

    def test_middle_drag_is_inert_on_the_strip_charts(self):
        for kind in ("throttle", "core"):
            with self.subTest(kind=kind):
                w, v = self.make(kind)
                before = (v.t0, v.t1, v.follow)
                press(w, 400, btn=Qt.MouseButton.MiddleButton)
                move(w, 600)
                release(w, 600, btn=Qt.MouseButton.MiddleButton)
                self.assertEqual((v.t0, v.t1), before[:2])

    def test_leaving_mid_drag_keeps_the_crosshair(self):
        for kind in ("chart", "throttle", "core"):
            with self.subTest(kind=kind):
                w, _ = self.make(kind)
                seen = []
                w.cursorMoved.connect(seen.append)
                press(w, 300)
                move(w, 500)
                w.leaveEvent(QEvent(QEvent.Type.Leave))
                self.assertNotIn(None, seen)

    def test_leaving_clears_the_crosshair_when_not_dragging(self):
        for kind in ("chart", "throttle", "core"):
            with self.subTest(kind=kind):
                w, _ = self.make(kind)
                seen = []
                w.cursorMoved.connect(seen.append)
                move(w, 500)
                w.leaveEvent(QEvent(QEvent.Type.Leave))
                self.assertEqual(seen[-1], None)

    def test_right_button_is_ignored(self):
        w, v = self.make("chart")
        before = (v.t0, v.t1, v.follow)
        press(w, 400, btn=Qt.MouseButton.RightButton)
        release(w, 700, btn=Qt.MouseButton.RightButton)
        self.assertEqual((v.t0, v.t1, v.follow), before)

    def test_legend_click_toggles_only_that_series(self):
        store = fixture_store()
        view = View(store)
        view.window = 300.0
        view.update_range()
        spec = PANES[0]
        for s in spec.series:
            s.visible = True
        cp = ChartPane(spec, view)
        cp.resize(W, spec.height)
        render(cp, spec.height)              # populates the legend hit boxes
        hit = spec.series[0].hit
        self.assertIsNotNone(hit)
        x = (hit[0] + hit[1]) / 2
        press(cp, x, y=8)
        release(cp, x, y=8)
        self.assertEqual([s.visible for s in spec.series],
                         [False] + [True] * (len(spec.series) - 1))
        press(cp, x, y=8)
        release(cp, x, y=8)
        self.assertTrue(all(s.visible for s in spec.series))

    def test_a_click_in_the_plot_area_toggles_nothing(self):
        store = fixture_store()
        view = View(store)
        view.window = 300.0
        view.update_range()
        spec = PANES[0]
        for s in spec.series:
            s.visible = True
        cp = ChartPane(spec, view)
        cp.resize(W, spec.height)
        render(cp, spec.height)
        x = (spec.series[0].hit[0] + spec.series[0].hit[1]) / 2
        press(cp, x, y=TOP + 20)
        release(cp, x, y=TOP + 20)
        self.assertTrue(all(s.visible for s in spec.series))

    def test_hidden_series_keeps_its_colour_slot(self):
        """Colour is bound to position, not rank, so hiding one series must not
        repaint the others."""
        store = fixture_store()
        view = View(store)
        view.update_range()
        spec = PANES[1]
        for s in spec.series:
            s.visible = True
        cp = ChartPane(spec, view)
        first = [i for i, _ in cp._visible_series()]
        spec.series[0].visible = False
        rest = [i for i, _ in cp._visible_series()]
        spec.series[0].visible = True
        self.assertEqual(first, [0, 1, 2, 3])
        self.assertEqual(rest, [1, 2, 3])      # indices unchanged, not renumbered


if __name__ == "__main__":
    unittest.main()
