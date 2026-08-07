"""Storage, the recording format, and the drawing maths.

All pure: no Qt beyond what render.py imports, no hardware, no clock.
"""

import math
import os
import tempfile
import unittest

import numpy as np

from amdgraph.render import (column_hold, fmt_time, fmt_val, nice_range,
                             polylines, time_ticks)
from amdgraph.session import Recorder, load_session, record_keys
from amdgraph.store import Store
from amdgraph.view import View


class TestView(unittest.TestCase):
    """The window every pane agrees on. Qt-free, so it tests as plain maths."""

    def store(self, n=100, step=1.0):
        st = Store()
        for i in range(n):
            st.append(i * step, {"a": float(i)})
        return st

    def test_following_pins_the_right_edge(self):
        v = View(self.store())
        v.window = 30.0
        v.update_range()
        self.assertAlmostEqual(v.t1, 99.0)
        self.assertAlmostEqual(v.t0, 69.0)

    def test_a_short_recording_still_fills_the_window(self):
        v = View(self.store(n=5))
        v.window = 60.0
        v.update_range()
        self.assertAlmostEqual(v.t1 - v.t0, 60.0)

    def test_all_mode_includes_the_overlay(self):
        v = View(self.store(n=10))
        v.window = 0.0
        v.overlay = self.store(n=50)
        v.update_range()
        self.assertGreaterEqual(v.t1, 49.0)

    def test_a_followed_window_ignores_a_longer_overlay(self):
        """The right edge tracks the live trace, not a recording that may run
        longer than this session has."""
        v = View(self.store(n=10))
        v.window = 30.0
        v.overlay = self.store(n=500)
        v.update_range()
        self.assertAlmostEqual(v.t1, 30.0)

    def test_zoom_to_stops_following(self):
        v = View(self.store())
        v.update_range()
        v.zoom_to(10.0, 40.0)
        self.assertEqual((v.t0, v.t1, v.follow), (10.0, 40.0, False))

    def test_zoom_to_refuses_a_degenerate_span(self):
        v = View(self.store())
        v.update_range()
        before = (v.t0, v.t1, v.follow)
        v.zoom_to(10.0, 10.5)
        self.assertEqual((v.t0, v.t1, v.follow), before)

    def test_unzoom_returns_to_following(self):
        v = View(self.store())
        v.window = 30.0
        v.zoom_to(1.0, 5.0)
        v.unzoom()
        self.assertTrue(v.follow)
        self.assertAlmostEqual(v.t1, 99.0)

    def test_zoom_at_keeps_the_point_under_the_pointer(self):
        v = View(self.store())
        v.window = 100.0
        v.update_range()
        t = v.t0 + (v.t1 - v.t0) * 0.25
        frac = (t - v.t0) / (v.t1 - v.t0)
        v.zoom_at(t, 0.5)
        self.assertAlmostEqual((t - v.t0) / (v.t1 - v.t0), frac, places=6)

    def test_zoom_is_clamped(self):
        v = View(self.store())
        v.update_range()
        for _ in range(50):
            v.zoom_at(50.0, 0.5)
        self.assertGreaterEqual(v.t1 - v.t0, 4.0)
        for _ in range(80):
            v.zoom_at(50.0, 1.25)
        self.assertLessEqual(v.t1 - v.t0, 86400.0)

    def test_pan_preserves_the_span(self):
        v = View(self.store())
        v.update_range()
        span = v.t1 - v.t0
        v.pan(-12.5)
        self.assertAlmostEqual(v.t1 - v.t0, span)
        self.assertFalse(v.follow)


class TestStore(unittest.TestCase):
    def test_append_and_read_back(self):
        st = Store(cap=4)
        for i in range(3):
            st.append(float(i), {"a": i * 10.0})
        self.assertEqual(st.n, 3)
        self.assertEqual(st.span(), (0.0, 2.0))
        self.assertEqual(list(st.col("a")), [0.0, 10.0, 20.0])

    def test_growth_preserves_and_pads_with_nan(self):
        st = Store(cap=2)
        for i in range(5):
            st.append(float(i), {"a": float(i)})
        self.assertEqual(st.n, 5)
        self.assertGreaterEqual(st.cap, 5)
        self.assertEqual(list(st.col("a")), [0.0, 1.0, 2.0, 3.0, 4.0])

    def test_a_key_that_appears_late_is_nan_before_it(self):
        st = Store(cap=8)
        st.append(0.0, {"a": 1.0})
        st.append(1.0, {"a": 2.0, "b": 9.0})
        b = st.col("b")
        self.assertTrue(math.isnan(b[0]))
        self.assertEqual(b[1], 9.0)

    def test_latest_walks_back_over_a_short_stall(self):
        st = Store()
        st.append(0.0, {"a": 5.0})
        for i in range(1, 4):
            st.append(float(i), {})            # sensor stalls
        self.assertEqual(st.latest("a"), 5.0)

    def test_latest_gives_up_on_a_long_stall(self):
        st = Store()
        st.append(0.0, {"a": 5.0})
        for i in range(1, 40):
            st.append(float(i), {})
        self.assertIsNone(st.latest("a"))

    def test_at_returns_the_sample_at_or_before(self):
        st = Store()
        for i in range(5):
            st.append(float(i), {"a": float(i)})
        self.assertEqual(st.at("a", 2.0), 2.0)
        self.assertEqual(st.at("a", 2.4), 2.0)

    def test_at_outside_the_span_is_none_not_the_nearest(self):
        """A crosshair parked past the end of a short trace must read as no
        data rather than silently repeating the last value."""
        st = Store()
        for i in range(5):
            st.append(float(i), {"a": float(i)})
        self.assertIsNone(st.at("a", 100.0))
        self.assertIsNone(st.at("a", -100.0))

    def test_empty_store(self):
        st = Store()
        self.assertEqual(st.span(), (0.0, 0.0))
        self.assertIsNone(st.col("a"))
        self.assertIsNone(st.latest("a"))
        self.assertIsNone(st.at("a", 0.0))

    def test_non_numeric_values_are_dropped(self):
        st = Store()
        st.append(0.0, {"a": 1.0, "fan_mode": "AUTO"})
        self.assertIsNone(st.col("fan_mode"))


class TestSession(unittest.TestCase):
    def round_trip(self, rows, markers=(), meta=None):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "s.csv")
        keys = sorted({k for r in rows for k in r})
        rec = Recorder(path, keys, meta or {"amdgraph": "session v1"})
        for i, r in enumerate(rows):
            rec.write(float(i), r)
        for t, label in markers:
            rec.mark(t, label)
        rec.close()
        return load_session(path), path

    def test_values_survive(self):
        st, _ = self.round_trip([{"a": 1.5, "b": 2.0}, {"a": 3.25, "b": 4.0}])
        self.assertEqual(st.n, 2)
        self.assertAlmostEqual(st.col("a")[1], 3.25, places=5)

    def test_gaps_stay_gaps(self):
        st, _ = self.round_trip([{"a": 1.0}, {"b": 2.0}])
        self.assertTrue(math.isnan(st.col("a")[1]))
        self.assertTrue(math.isnan(st.col("b")[0]))

    def test_markers_and_meta(self):
        st, _ = self.round_trip([{"a": 1.0}], markers=[(0.5, "flipped it")],
                                meta={"amdgraph": "session v1", "host": "x"})
        self.assertEqual(st.markers, [(0.5, "flipped it")])
        self.assertEqual(st.meta["host"], "x")

    def test_marker_with_no_label(self):
        st, _ = self.round_trip([{"a": 1.0}], markers=[(0.5, "")])
        self.assertEqual(st.markers, [(0.5, "")])

    def test_comment_lines_are_skipped_by_other_readers(self):
        _, path = self.round_trip([{"a": 1.0}], markers=[(0.5, "m")])
        with open(path) as f:
            body = [l for l in f if not l.startswith("#")]
        self.assertEqual(body[0].strip(), "t,a")

    def test_rejects_a_file_that_is_not_a_recording(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "x.csv")
        open(p, "w").write("time,value\n1,2\n")
        with self.assertRaises(ValueError):
            load_session(p)
        open(p, "w").write("# only a comment\n")
        with self.assertRaises(ValueError):
            load_session(p)

    def test_record_keys_are_unique_and_cover_the_plotted_ones(self):
        keys = record_keys()
        self.assertEqual(len(keys), len(set(keys)))
        for k in ("stapm", "stapm_lim", "core_power_sum", "pwr_socket",
                  "pwr_soc", "thr0", "thr12", "ec_skin", "lapmode", "palm"):
            self.assertIn(k, keys)

    def test_record_keys_excludes_the_one_string_field(self):
        # fan_mode is text; the CSV writer would emit it as blank anyway.
        self.assertNotIn("fan_mode", record_keys())


class TestAxisMaths(unittest.TestCase):
    def test_nice_range_contains_the_data(self):
        for lo, hi in ((0.0, 1.0), (3.2, 7.9), (-40.0, 12.0), (0.0, 12345.0)):
            a, b = nice_range(lo, hi, floor0=False)
            self.assertLessEqual(a, lo)
            self.assertGreaterEqual(b, hi)

    def test_floor0_pins_the_bottom(self):
        self.assertEqual(nice_range(5.0, 20.0, floor0=True)[0], 0.0)

    def test_flat_and_non_finite_inputs(self):
        a, b = nice_range(7.0, 7.0, floor0=False)
        self.assertLess(a, b)
        self.assertEqual(nice_range(math.nan, 1.0, floor0=False), (0.0, 1.0))
        self.assertEqual(nice_range(0.0, math.inf, floor0=False), (0.0, 1.0))

    def test_range_is_stable_under_small_excursions(self):
        """An axis that re-fits every frame makes the trace appear to move when
        it has not."""
        base = nice_range(0.0, 20.0, floor0=True)
        self.assertEqual(nice_range(0.0, 20.5, floor0=True), base)

    def test_fmt_val(self):
        self.assertEqual(fmt_val(None, "W"), "--")
        self.assertEqual(fmt_val(1.2345, "V"), "1.234")     # volts: 3 dp
        self.assertEqual(fmt_val(2700.0, "MHz"), "2700")    # clocks: integer
        self.assertEqual(fmt_val(123.4, "W"), "123")
        self.assertEqual(fmt_val(12.34, "W"), "12.3")
        self.assertEqual(fmt_val(1.234, "W"), "1.23")

    def test_fmt_time(self):
        self.assertEqual(fmt_time(0), "0:00")
        self.assertEqual(fmt_time(75), "1:15")
        self.assertEqual(fmt_time(3725), "1:02:05")

    def test_time_ticks_are_round_and_bounded(self):
        for span in (10, 60, 300, 3600, 86400):
            ticks = time_ticks(0.0, float(span))
            self.assertTrue(ticks)
            self.assertLessEqual(len(ticks), 32)
            step = ticks[1] - ticks[0] if len(ticks) > 1 else span
            for t in ticks:
                self.assertAlmostEqual(t % step, 0.0, places=6)

    def test_time_ticks_stay_put_as_the_window_scrolls(self):
        a = set(time_ticks(0.0, 300.0))
        b = set(time_ticks(10.0, 310.0))
        self.assertTrue(a & b)


class TestColumnHold(unittest.TestCase):
    def test_value_is_held_until_the_next_sample(self):
        vals, valid = column_hold(np.array([0, 4]), np.array([1.0, 2.0]), 8)
        self.assertTrue(valid[:5].all())
        self.assertEqual(list(vals[0:4]), [1.0] * 4)
        self.assertEqual(vals[4], 2.0)

    def test_nothing_is_painted_past_the_last_sample(self):
        _, valid = column_hold(np.array([0, 2]), np.array([1.0, 1.0]), 8)
        self.assertFalse(valid[3:].any())

    def test_worst_wins_a_shared_column(self):
        vals, _ = column_hold(np.array([1, 1, 1]),
                              np.array([0.2, 0.9, 0.5]), 4)
        self.assertEqual(vals[1], 0.9)

    def test_empty(self):
        vals, valid = column_hold(np.array([], dtype=int),
                                  np.array([]), 4)
        self.assertFalse(valid.any())
        self.assertEqual(vals.shape, (4,))


class TestPolylines(unittest.TestCase):
    def px(self, ys):
        return np.arange(len(ys), dtype=float), np.array(ys, dtype=float)

    def test_a_simple_run_is_one_polyline(self):
        x, y = self.px([1.0, 2.0, 3.0])
        polys = polylines(x, y, 0.0, 100)
        self.assertEqual(len(polys), 1)
        self.assertEqual(polys[0].count(), 3)

    def test_nan_splits_the_trace(self):
        """A sensor that vanishes must leave a hole, not a cliff to the floor."""
        x, y = self.px([1.0, 2.0, math.nan, 4.0, 5.0])
        self.assertEqual(len(polylines(x, y, 0.0, 100)), 2)

    def test_a_lone_sample_is_still_visible(self):
        x, y = self.px([math.nan, 3.0, math.nan])
        polys = polylines(x, y, 0.0, 100)
        self.assertEqual(len(polys), 1)
        self.assertEqual(polys[0].count(), 2)      # widened so it can be seen

    def test_all_nan_and_empty_draw_nothing(self):
        x, y = self.px([math.nan, math.nan])
        self.assertEqual(polylines(x, y, 0.0, 100), [])
        self.assertEqual(polylines(np.array([]), np.array([]), 0.0, 100), [])

    def test_dense_data_decimates_but_keeps_the_spike(self):
        n = 5000
        x = np.linspace(0, 99, n)
        y = np.full(n, 10.0)
        y[2500] = 999.0                             # one-sample excursion
        polys = polylines(x, y, 0.0, 100)
        peak = max(p.at(i).y() for p in polys for i in range(p.count()))
        self.assertEqual(peak, 999.0)
        self.assertLess(sum(p.count() for p in polys), n)


if __name__ == "__main__":
    unittest.main()
