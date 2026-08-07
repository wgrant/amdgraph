"""Storage, the view window, the recording format, and the drawing maths.

All pure: no hardware, no clock, and no Qt beyond what render.py imports.
"""

import math

import numpy as np
import pytest

from amdgraph.render import (column_hold, fmt_time, fmt_val, nice_range,
                             polylines, time_ticks)
from amdgraph.session import Recorder, load_session, record_keys
from amdgraph.store import Store
from amdgraph.view import View


def ramp(n=100, step=1.0):
    st = Store()
    for i in range(n):
        st.append(i * step, {"a": float(i)})
    return st


class TestStore:
    def test_append_and_read_back(self):
        st = Store(cap=4)
        for i in range(3):
            st.append(float(i), {"a": i * 10.0})
        assert st.n == 3
        assert st.span() == (0.0, 2.0)
        assert list(st.col("a")) == [0.0, 10.0, 20.0]

    def test_growth_preserves_the_data(self):
        st = Store(cap=2)
        for i in range(5):
            st.append(float(i), {"a": float(i)})
        assert st.n == 5 and st.cap >= 5
        assert list(st.col("a")) == [0.0, 1.0, 2.0, 3.0, 4.0]

    def test_a_key_that_appears_late_is_nan_before_it(self):
        st = Store(cap=8)
        st.append(0.0, {"a": 1.0})
        st.append(1.0, {"a": 2.0, "b": 9.0})
        assert math.isnan(st.col("b")[0])
        assert st.col("b")[1] == 9.0

    def test_latest_walks_back_over_a_short_stall(self):
        st = Store()
        st.append(0.0, {"a": 5.0})
        for i in range(1, 4):
            st.append(float(i), {})            # sensor stalls
        assert st.latest("a") == 5.0

    def test_latest_gives_up_on_a_long_stall(self):
        st = Store()
        st.append(0.0, {"a": 5.0})
        for i in range(1, 40):
            st.append(float(i), {})
        assert st.latest("a") is None

    @pytest.mark.parametrize("t, want", [(2.0, 2.0), (2.4, 2.0), (0.0, 0.0)])
    def test_at_returns_the_sample_at_or_before(self, t, want):
        assert ramp(5).at("a", t) == want

    @pytest.mark.parametrize("t", [100.0, -100.0])
    def test_at_outside_the_span_is_none_not_the_nearest(self, t):
        """A crosshair parked past the end of a short trace must read as no
        data rather than silently repeating the last value."""
        assert ramp(5).at("a", t) is None

    def test_empty_store(self):
        st = Store()
        assert st.span() == (0.0, 0.0)
        assert st.col("a") is None
        assert st.latest("a") is None
        assert st.at("a", 0.0) is None

    def test_non_numeric_values_are_dropped(self):
        st = Store()
        st.append(0.0, {"a": 1.0, "fan_mode": "AUTO"})
        assert st.col("fan_mode") is None


class TestView:
    def test_following_pins_the_right_edge(self):
        v = View(ramp())
        v.window = 30.0
        v.update_range()
        assert v.t1 == pytest.approx(99.0)
        assert v.t0 == pytest.approx(69.0)

    def test_a_short_recording_still_fills_the_window(self):
        v = View(ramp(n=5))
        v.window = 60.0
        v.update_range()
        assert v.t1 - v.t0 == pytest.approx(60.0)

    def test_all_mode_includes_the_overlay(self):
        v = View(ramp(n=10))
        v.window = 0.0
        v.overlay = ramp(n=50)
        v.update_range()
        assert v.t1 >= 49.0

    def test_a_followed_window_ignores_a_longer_overlay(self):
        """The right edge tracks the live trace, not a recording that may run
        longer than this session has."""
        v = View(ramp(n=10))
        v.window = 30.0
        v.overlay = ramp(n=500)
        v.update_range()
        assert v.t1 == pytest.approx(30.0)

    def test_zoom_to_stops_following(self):
        v = View(ramp())
        v.update_range()
        v.zoom_to(10.0, 40.0)
        assert (v.t0, v.t1, v.follow) == (10.0, 40.0, False)

    def test_zoom_to_refuses_a_degenerate_span(self):
        v = View(ramp())
        v.update_range()
        before = (v.t0, v.t1, v.follow)
        v.zoom_to(10.0, 10.5)
        assert (v.t0, v.t1, v.follow) == before

    def test_unzoom_returns_to_following(self):
        v = View(ramp())
        v.window = 30.0
        v.zoom_to(1.0, 5.0)
        v.unzoom()
        assert v.follow and v.t1 == pytest.approx(99.0)

    def test_zoom_at_keeps_the_point_under_the_pointer(self):
        v = View(ramp())
        v.window = 100.0
        v.update_range()
        t = v.t0 + (v.t1 - v.t0) * 0.25
        frac = (t - v.t0) / (v.t1 - v.t0)
        v.zoom_at(t, 0.5)
        assert (t - v.t0) / (v.t1 - v.t0) == pytest.approx(frac)

    def test_zoom_is_clamped_both_ways(self):
        v = View(ramp())
        v.update_range()
        for _ in range(50):
            v.zoom_at(50.0, 0.5)
        assert v.t1 - v.t0 >= 4.0
        for _ in range(80):
            v.zoom_at(50.0, 1.25)
        assert v.t1 - v.t0 <= 86400.0

    def test_pan_preserves_the_span(self):
        v = View(ramp())
        v.update_range()
        span = v.t1 - v.t0
        v.pan(-12.5)
        assert v.t1 - v.t0 == pytest.approx(span)
        assert not v.follow


class TestSession:
    @pytest.fixture
    def round_trip(self, tmp_path):
        def run(rows, markers=(), meta=None):
            path = str(tmp_path / "s.csv")
            keys = sorted({k for r in rows for k in r})
            rec = Recorder(path, keys, meta or {"amdgraph": "session v1"})
            for i, r in enumerate(rows):
                rec.write(float(i), r)
            for t, label in markers:
                rec.mark(t, label)
            rec.close()
            return load_session(path), path
        return run

    def test_values_survive(self, round_trip):
        st, _ = round_trip([{"a": 1.5, "b": 2.0}, {"a": 3.25, "b": 4.0}])
        assert st.n == 2
        assert st.col("a")[1] == pytest.approx(3.25, abs=1e-5)

    def test_gaps_stay_gaps(self, round_trip):
        st, _ = round_trip([{"a": 1.0}, {"b": 2.0}])
        assert math.isnan(st.col("a")[1])
        assert math.isnan(st.col("b")[0])

    def test_markers_and_meta(self, round_trip):
        st, _ = round_trip([{"a": 1.0}], markers=[(0.5, "flipped it")],
                           meta={"amdgraph": "session v1", "host": "x"})
        assert st.markers == [(0.5, "flipped it")]
        assert st.meta["host"] == "x"

    def test_marker_with_no_label(self, round_trip):
        st, _ = round_trip([{"a": 1.0}], markers=[(0.5, "")])
        assert st.markers == [(0.5, "")]

    def test_comment_lines_are_skippable_by_other_readers(self, round_trip):
        _, path = round_trip([{"a": 1.0}], markers=[(0.5, "m")])
        with open(path) as f:
            body = [l for l in f if not l.startswith("#")]
        assert body[0].strip() == "t,a"

    @pytest.mark.parametrize("text", ["time,value\n1,2\n", "# only a comment\n"])
    def test_rejects_a_file_that_is_not_a_recording(self, tmp_path, text):
        p = tmp_path / "x.csv"
        p.write_text(text)
        with pytest.raises(ValueError):
            load_session(str(p))

    def test_close_is_idempotent(self, tmp_path):
        """flush() on an already-closed file raises ValueError, not OSError,
        and the second close arrives from a Qt virtual override where an
        exception aborts the process."""
        rec = Recorder(str(tmp_path / "s.csv"), ["a"], {})
        rec.write(0.0, {"a": 1.0})
        rec.close()
        rec.close()                            # must not raise

    def test_record_keys_are_unique(self):
        keys = record_keys()
        assert len(keys) == len(set(keys))

    @pytest.mark.parametrize("key", [
        "stapm", "stapm_lim", "core_power_sum", "pwr_socket", "pwr_soc",
        "thr0", "thr12", "ec_skin", "lapmode", "palm"])
    def test_record_keys_cover_the_plotted_ones(self, key):
        assert key in record_keys()

    def test_record_keys_excludes_the_one_string_field(self):
        # fan_mode is text; the CSV writer would emit it as blank anyway.
        assert "fan_mode" not in record_keys()


class TestAxisMaths:
    @pytest.mark.parametrize("lo, hi", [
        (0.0, 1.0), (3.2, 7.9), (-40.0, 12.0), (0.0, 12345.0)])
    def test_nice_range_contains_the_data(self, lo, hi):
        a, b = nice_range(lo, hi, floor0=False)
        assert a <= lo and b >= hi

    def test_floor0_pins_the_bottom(self):
        assert nice_range(5.0, 20.0, floor0=True)[0] == 0.0

    def test_flat_input_still_gives_a_range(self):
        a, b = nice_range(7.0, 7.0, floor0=False)
        assert a < b

    @pytest.mark.parametrize("lo, hi", [(math.nan, 1.0), (0.0, math.inf)])
    def test_non_finite_input(self, lo, hi):
        assert nice_range(lo, hi, floor0=False) == (0.0, 1.0)

    def test_range_is_stable_under_small_excursions(self):
        """An axis that re-fits every frame makes the trace appear to move when
        it has not."""
        assert nice_range(0.0, 20.5, True) == nice_range(0.0, 20.0, True)

    @pytest.mark.parametrize("v, unit, want", [
        (None, "W", "--"),
        (1.2345, "V", "1.234"),        # volts get 3 dp
        (2700.0, "MHz", "2700"),       # clocks are integers
        (123.4, "W", "123"),
        (12.34, "W", "12.3"),
        (1.234, "W", "1.23"),
    ])
    def test_fmt_val(self, v, unit, want):
        assert fmt_val(v, unit) == want

    @pytest.mark.parametrize("t, want", [(0, "0:00"), (75, "1:15"),
                                         (3725, "1:02:05")])
    def test_fmt_time(self, t, want):
        assert fmt_time(t) == want

    @pytest.mark.parametrize("span", [10, 60, 300, 3600, 86400])
    def test_time_ticks_are_round_and_bounded(self, span):
        ticks = time_ticks(0.0, float(span))
        assert ticks and len(ticks) <= 32
        step = ticks[1] - ticks[0] if len(ticks) > 1 else span
        for t in ticks:
            assert t % step == pytest.approx(0.0, abs=1e-6)

    def test_time_ticks_stay_put_as_the_window_scrolls(self):
        assert set(time_ticks(0.0, 300.0)) & set(time_ticks(10.0, 310.0))


class TestColumnHold:
    def test_value_is_held_until_the_next_sample(self):
        vals, valid = column_hold(np.array([0, 4]), np.array([1.0, 2.0]), 8)
        assert valid[:5].all()
        assert list(vals[0:4]) == [1.0] * 4
        assert vals[4] == 2.0

    def test_nothing_is_painted_past_the_last_sample(self):
        _, valid = column_hold(np.array([0, 2]), np.array([1.0, 1.0]), 8)
        assert not valid[3:].any()

    def test_worst_wins_a_shared_column(self):
        vals, _ = column_hold(np.array([1, 1, 1]), np.array([0.2, 0.9, 0.5]), 4)
        assert vals[1] == 0.9

    def test_empty(self):
        vals, valid = column_hold(np.array([], dtype=int), np.array([]), 4)
        assert not valid.any() and vals.shape == (4,)


class TestPolylines:
    @staticmethod
    def px(ys):
        return np.arange(len(ys), dtype=float), np.array(ys, dtype=float)

    def test_a_simple_run_is_one_polyline(self):
        polys = polylines(*self.px([1.0, 2.0, 3.0]), 0.0, 100)
        assert len(polys) == 1 and polys[0].count() == 3

    def test_nan_splits_the_trace(self):
        """A sensor that vanishes must leave a hole, not a cliff to the floor."""
        polys = polylines(*self.px([1.0, 2.0, math.nan, 4.0, 5.0]), 0.0, 100)
        assert len(polys) == 2

    def test_a_lone_sample_is_still_visible(self):
        polys = polylines(*self.px([math.nan, 3.0, math.nan]), 0.0, 100)
        assert len(polys) == 1 and polys[0].count() == 2      # widened

    def test_all_nan_draws_nothing(self):
        assert polylines(*self.px([math.nan, math.nan]), 0.0, 100) == []

    def test_empty_draws_nothing(self):
        assert polylines(np.array([]), np.array([]), 0.0, 100) == []

    def test_dense_data_decimates_but_keeps_the_spike(self):
        n = 5000
        x = np.linspace(0, 99, n)
        y = np.full(n, 10.0)
        y[2500] = 999.0                             # one-sample excursion
        polys = polylines(x, y, 0.0, 100)
        peak = max(p.at(i).y() for p in polys for i in range(p.count()))
        assert peak == 999.0
        assert sum(p.count() for p in polys) < n
