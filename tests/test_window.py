"""The window, driven with no hardware present.

This layer had no tests at all until the source became injectable, which is the
same change that makes a second platform possible: everything below is exercised
against a FakeSource, so none of it depends on this machine being a Phoenix.
"""

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from amdgraph.panes import CAP_RATES, HEAT_AFTER, PANES        # noqa: E402
from amdgraph.rasters import CorePane, ThrottlePane            # noqa: E402
from amdgraph.session import load_session                      # noqa: E402
from amdgraph.view import View                                 # noqa: E402


class TestAssembly:
    def test_every_pane_in_the_catalogue_is_built(self, main):
        titles = [p.spec.title for p in main.panes if hasattr(p, "spec")]
        assert titles == [s.title for s in PANES]

    def test_cap_reason_is_first_and_the_heat_strip_follows_cpu_clock(self,
                                                                     main):
        assert isinstance(main.panes[0], ThrottlePane)
        titles = [getattr(p, "spec", None) and p.spec.title for p in main.panes]
        assert titles[titles.index(HEAT_AFTER) + 1] is None
        assert isinstance(main.panes[titles.index(HEAT_AFTER) + 1], CorePane)

    def test_only_the_top_pane_labels_markers(self, main):
        assert main.panes[0].label_markers
        assert not any(p.label_markers for p in main.panes[1:])

    def test_every_pane_shares_one_view(self, main):
        assert all(p.view is main.view for p in main.panes)
        assert main.axis.view is main.view

    def test_nothing_in_the_toolbar_steals_the_space_key(self, main):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QWidget
        bar = main.centralWidget().layout().itemAt(0).widget()
        for w in bar.findChildren(QWidget):
            assert w.focusPolicy() == Qt.FocusPolicy.NoFocus


class TestSampling:
    def test_construction_takes_one_sample(self, main, source):
        assert source.ticks == 1
        assert main.store.n == 1

    def test_tick_appends(self, main, source):
        for _ in range(4):
            main.tick()
        assert source.ticks == 5
        assert main.store.n == 5
        assert main.store.latest("stapm") == 50.0

    def test_freeze_holds_the_view_but_keeps_sampling(self, main, source):
        main.on_pause(True)
        before = (main.view.t0, main.view.t1)
        for _ in range(3):
            main.tick()
        assert source.ticks == 4              # still sampling
        assert main.view.frozen and not main.view.follow
        assert (main.view.t0, main.view.t1) == before
        assert main.btn_pause.text() == "Resume"

    def test_browsing_a_recording_stops_sampling(self, main, source, tmp_path):
        path = self._record(main, tmp_path)
        before = source.ticks
        main.open_session(path)
        main.tick()
        assert source.ticks == before         # live sampling suspended

    @staticmethod
    def _record(main, tmp_path):
        main.on_record(True)
        for _ in range(3):
            main.tick()
        path = main.recorder.path
        main.on_record(False)
        return path


class TestRecording:
    def test_round_trip_through_the_real_writer(self, main, tmp_path):
        main.on_record(True)
        assert main.btn_rec.text() == "■ Stop"
        for _ in range(3):
            main.tick()
        path = main.recorder.path
        main.on_record(False)
        assert main.recorder is None
        assert main.btn_rec.text() == "● Record"

        st = load_session(path)
        assert st.n == 3
        assert st.meta["amdgraph"] == "session v1"

    def test_source_supplies_its_own_header_fields(self, main, source):
        source._meta = {"pm_table_version": "0xdeadbeef", "backend": "fake"}
        main.on_record(True)
        main.tick()
        path = main.recorder.path
        main.on_record(False)
        meta = load_session(path).meta
        assert meta["pm_table_version"] == "0xdeadbeef"
        assert meta["backend"] == "fake"
        assert meta["interval"] == "0.5"

    def test_recordings_land_in_the_configured_directory(self, main, tmp_path):
        main.on_record(True)
        path = main.recorder.path
        main.on_record(False)
        assert path.startswith(str(tmp_path))

    def test_an_unwritable_directory_warns_instead_of_raising(self, main,
                                                              monkeypatch):
        from amdgraph import window as W
        monkeypatch.setattr(W, "DATA_DIR", "/proc/nope/amdgraph")
        main.btn_rec.setChecked(True)         # triggers on_record(True)
        assert main.recorder is None
        assert not main.btn_rec.isChecked()
        assert main.warned                    # the user was told

    def test_a_marker_reaches_both_the_view_and_the_file(self, main):
        main.on_record(True)
        main.tick()
        main.on_mark()
        path = main.recorder.path
        main.on_record(False)
        assert main.view.markers and main.view.markers[0][1] == "a marker"
        assert load_session(path).markers[0][1] == "a marker"

    def test_a_marker_lands_on_the_data_axis_not_the_wall_clock(self, main):
        for _ in range(5):
            main.tick()
        main.on_mark()
        t = main.view.markers[0][0]
        assert t == pytest.approx(main.store.span()[1])

    def test_closing_flushes_the_recording(self, main):
        main.on_record(True)
        main.tick()
        path = main.recorder.path
        main.close()
        assert load_session(path).n >= 1


class TestSessions:
    @pytest.fixture
    def recorded(self, main, tmp_path):
        main.on_record(True)
        for _ in range(4):
            main.tick()
        path = main.recorder.path
        main.on_record(False)
        return path

    def test_open_switches_the_view_but_keeps_the_live_buffer(self, main,
                                                              recorded):
        live = main.store
        main.open_session(recorded)
        assert not main.live
        assert main.view.store is not live
        assert main.store is live             # still there, still ours
        assert main.btn_golive.isEnabled()
        assert "amdgraph —" in main.windowTitle()

    def test_go_live_switches_back(self, main, recorded):
        main.open_session(recorded)
        main.go_live()
        assert main.live
        assert main.view.store is main.store
        assert not main.btn_golive.isEnabled()
        assert main.windowTitle() == "amdgraph"

    def test_open_shows_the_whole_recording(self, main, recorded):
        main.open_session(recorded)
        assert main.view.window == 0.0

    def test_overlay_draws_behind_without_replacing(self, main, recorded,
                                                    monkeypatch):
        monkeypatch.setattr(type(main), "_pick", lambda self: recorded)
        live = main.view.store
        main.on_overlay()
        assert main.view.overlay is not None
        assert main.view.store is live
        assert main.btn_clear.isEnabled()
        main.on_clear_overlay()
        assert main.view.overlay is None
        assert not main.btn_clear.isEnabled()

    @pytest.mark.parametrize("body", ["not a recording at all\n", ""])
    def test_a_bad_file_warns_and_changes_nothing(self, main, tmp_path, body):
        p = tmp_path / "bad.csv"
        p.write_text(body)
        main.open_session(str(p))
        assert main.live                      # unchanged
        assert main.warned

    def test_a_missing_file_warns(self, main):
        main.open_session("/nope/nothing.csv")
        assert main.live and main.warned

    def test_markers_come_back_with_the_recording(self, main, recorded):
        main.on_mark()
        main.open_session(recorded)
        # The reloaded session has its own markers, not the live ones.
        assert main.view.markers == list(main.view.store.markers)


class TestHandlers:
    def test_reset_clears_the_buffer_and_the_source(self, main, source):
        for _ in range(5):
            main.tick()
        main.on_reset()
        assert main.store.n == 0
        assert source.resets == 1
        assert main.view.store is main.store

    def test_reset_while_browsing_leaves_the_view_alone(self, main, tmp_path):
        main.on_record(True)
        main.tick()
        path = main.recorder.path
        main.on_record(False)
        main.open_session(path)
        viewed = main.view.store
        main.on_reset()
        assert main.view.store is viewed      # still the recording

    @pytest.mark.parametrize("i, seconds", list(enumerate(
        [w[0] for w in View.WINDOWS])))
    def test_window_selector(self, main, i, seconds):
        main.on_window(i)
        assert main.view.window == float(seconds)
        assert main.view.follow

    @pytest.mark.parametrize("i, hz", list(enumerate(r[0] for r in CAP_RATES)))
    def test_cap_rate_reaches_the_source(self, main, source, i, hz):
        main.on_cap_rate(i)
        assert source.cap_rates[-1] == hz

    def test_cursor_is_applied_immediately(self, main):
        main.on_cursor(12.5)
        assert main.view.cursor == 12.5
        main.on_cursor(None)
        assert main.view.cursor is None

    def test_cursor_updates_are_coalesced(self, main):
        """Mouse moves arrive far faster than the eye can use; without this the
        pointer sweeping the window repaints every pane per event."""
        main._cursor_pending = False
        main.on_cursor(1.0)
        assert main._cursor_pending
        main.on_cursor(2.0)                   # no second timer armed
        assert main.view.cursor == 2.0
        main._flush_cursor()
        assert not main._cursor_pending

    def test_follow_toggle(self, main):
        main.on_follow(False)
        assert not main.view.follow
        main.on_follow(True)
        assert main.view.follow

    def test_closing_shuts_the_source_down(self, main, source):
        main.close()
        assert source.closed == 1

    def test_closing_twice_is_safe(self, main, source):
        """Qt can deliver closeEvent more than once. It used to abort the
        process: the recorder was left set, its second close hit flush() on a
        closed file, and the ValueError escaped a virtual override."""
        main.on_record(True)
        main.tick()
        main.close()
        main.close()
        assert main.recorder is None
        assert source.closed == 2


class TestStatus:
    def test_live(self, main):
        main.update_status()
        text = main.status.text()
        assert "live · 0.5s" in text
        assert "samples" in text and "span" in text

    def test_frozen(self, main):
        main.on_pause(True)
        assert "FROZEN" in main.status.text()

    def test_recording_names_the_file(self, main):
        main.on_record(True)
        assert "recording →" in main.status.text()
        main.on_record(False)

    def test_zoomed(self, main):
        for _ in range(20):
            main.tick()
        main.view.zoom_to(1.0, 5.0)
        main.update_status()
        assert "Esc to follow again" in main.status.text()

    def test_browsing_names_the_session(self, main, tmp_path):
        main.on_record(True)
        main.tick()
        path = main.recorder.path
        main.on_record(False)
        main.open_session(path)
        assert os.path.basename(path) in main.status.text()

    def test_source_notes_are_surfaced(self, qapp, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QMessageBox

        from amdgraph import window as W
        from conftest import FakeSource
        monkeypatch.setattr(W, "DATA_DIR", str(tmp_path))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(
            lambda *a, **k: None))
        src = FakeSource(notes=["ryzen_smu not loaded", "gpu_metrics v3_0"])
        w = W.Main(interval=0.5, source=src)
        w.timer.stop()
        try:
            assert "ryzen_smu not loaded" in w.status.text()
            assert "gpu_metrics v3_0" in w.status.text()
        finally:
            w.close()


class TestRefresh:
    def test_refresh_paints_nothing_that_is_off_screen(self, main):
        # Nothing is shown, so every pane's visibleRegion is empty and refresh
        # should be a no-op rather than a full repaint of the column.
        main.refresh()

    def test_a_full_render_of_the_window_does_not_raise(self, main):
        from PyQt6.QtGui import QImage
        for _ in range(10):
            main.tick()
        main.resize(1180, 900)
        img = QImage(1180, 900, QImage.Format.Format_ARGB32)
        img.fill(0)
        main.render(img)
