"""The window, driven with no hardware present.

This layer had no tests at all until the source became injectable, which is the
same change that makes a second platform possible: everything below is exercised
against a FakeSource, so none of it depends on this machine being a Phoenix.
"""

import os

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from amdgraph.panes import (CAP_RATES, GROUPS, HEAT_AFTER,     # noqa: E402
                            PANES, available_catalogue)
from amdgraph.rasters import CorePane, ThrottlePane            # noqa: E402
from amdgraph.session import load_session                      # noqa: E402
from amdgraph.view import View                                 # noqa: E402


class TestAssembly:
    def test_every_pane_in_the_catalogue_is_built(self, main):
        titles = [p.spec.title for p in main.panes if p.spec]
        assert titles == [s.title for s in PANES]

    def test_cap_reason_is_first_and_the_heat_strip_follows_cpu_clock(self,
                                                                     main):
        assert isinstance(main.panes[0].body, ThrottlePane)
        titles = [p.spec.title if p.spec else None for p in main.panes]
        at = titles.index(HEAT_AFTER) + 1
        assert titles[at] is None
        assert isinstance(main.panes[at].body, CorePane)

    def test_only_the_top_pane_labels_markers(self, main):
        assert main.panes[0].label_markers
        assert not any(p.label_markers for p in main.panes[1:])

    def test_every_pane_shares_one_view(self, main):
        assert all(p.body.view is main.view for p in main.panes)
        assert main.axis.view is main.view

    def test_nothing_in_the_toolbar_steals_the_space_key(self, main):
        """A focused button consumes Space before the shortcut sees it, and
        Space is now the only way to freeze."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QWidget
        assert main.toolbar.focusPolicy() == Qt.FocusPolicy.NoFocus
        for w in main.toolbar.findChildren(QWidget):
            assert w.focusPolicy() == Qt.FocusPolicy.NoFocus, w

    def test_the_toolbar_overflows_rather_than_forcing_a_width(self, main):
        """The whole point of using a real QToolBar: below a certain width Qt
        moves controls into an extension popup instead of refusing to shrink,
        so the chrome stops setting the window's minimum."""
        main.resize(320, 700)
        main.show()
        assert main.minimumSizeHint().width() <= 320

    def test_unowned_series_and_empty_panes_are_absent(self):
        panes, groups = available_catalogue({"stapm", "stapm_lim",
                                             "core_freq_mean"})
        assert [p.title for p in panes] == ["Package power", "CPU clock"]
        assert [s.label for s in panes[0].series] == ["STAPM"]
        assert groups == []


class TestSections:
    """A collapsed group hides panes; it must not stop them existing. They keep
    getting data, so expanding one shows the history you did not watch being
    recorded rather than an empty pane that starts from now."""

    def members(self, main, group):
        return [p for p in main.panes
                if p.spec and p.spec.title in group.titles]

    def test_declared_groups_get_a_header(self, main):
        assert len(main.sections) == len(GROUPS)
        assert [s.group.title for s in main.sections] == [g.title
                                                          for g in GROUPS]

    def test_collapsed_by_default_hides_its_panes(self, main):
        for section in main.sections:
            if section.group.collapsed:
                assert not section.expanded
                assert all(p.isHidden() for p in
                           self.members(main, section.group))

    def test_toggling_the_header_shows_and_hides(self, main):
        section = main.sections[0]
        members = self.members(main, section.group)
        assert members
        section.set_expanded(True)
        assert all(not p.isHidden() for p in members)
        section.set_expanded(False)
        assert all(p.isHidden() for p in members)

    def test_hidden_panes_still_receive_samples(self, main):
        section = main.sections[0]
        for _ in range(5):
            main.tick()
        section.set_expanded(True)
        # The panes read the shared store, so there is nothing per-pane to
        # catch up: the history is simply there.
        assert main.store.n == 6
        assert all(p.body.view is main.view
                   for p in self.members(main, section.group))

    def test_grouped_panes_are_indented(self, main):
        from amdgraph import render
        section = main.sections[0]
        inside = self.members(main, section.group)
        outside = [p for p in main.panes if p not in inside]
        assert all(p._indent == render.INDENT for p in inside)
        assert all(p._indent == 0 for p in outside)

    def test_indenting_does_not_move_the_plot(self, main):
        """Every pane shares one time axis. If an indented pane's plot moved
        with its frame, its gridlines and crosshair would stop lining up with
        the ruler and with the panes above it -- so the body gives the indent
        back out of its own gutter."""
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QApplication
        main.sections[0].set_expanded(True)
        main.resize(1180, 900)
        main.show()
        QApplication.instance().processEvents()

        lefts, rights = set(), set()
        for f in main.panes:
            b, r = f.body, f.body.plot_rect()
            lefts.add(b.mapToGlobal(QPoint(int(r.left()), 0)).x())
            rights.add(b.mapToGlobal(QPoint(int(r.right()), 0)).x())
        assert len(lefts) == 1, f"plot left edges disagree: {sorted(lefts)}"
        assert len(rights) == 1, f"plot right edges disagree: {sorted(rights)}"

    def test_a_collapsed_group_leaves_the_column_shorter(self, main):
        section = main.sections[0]
        section.set_expanded(False)
        short = sum(p.height() for p in main.panes if not p.isHidden())
        section.set_expanded(True)
        tall = sum(p.height() for p in main.panes if not p.isHidden())
        assert tall > short

    def test_refresh_and_render_work_either_way(self, main):
        from PyQt6.QtGui import QImage
        for expanded in (False, True, False):
            main.sections[0].set_expanded(expanded)
            main.tick()
            main.refresh()
            img = QImage(700, 900, QImage.Format.Format_ARGB32)
            img.fill(0)
            main.resize(700, 900)
            main.render(img)


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
        assert "FROZEN" in main.status.text()

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
        assert not main.btn_golive.isHidden()
        assert "amdgraph —" in main.windowTitle()

    def test_go_live_switches_back(self, main, recorded):
        main.open_session(recorded)
        main.go_live()
        assert main.live
        assert main.view.store is main.store
        assert main.btn_golive.isHidden()
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
        assert main.btn_overlay.text() == "Clear overlay"
        # The same button now drops it -- the two actions are never both valid.
        main.btn_overlay.click()
        assert main.view.overlay is None
        assert main.btn_overlay.text() == "Overlay…"

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

    @pytest.mark.parametrize("hz", [r[0] for r in CAP_RATES])
    def test_cap_rate_reaches_the_source(self, main, source, hz):
        """The control lives on the Cap reason pane's context menu now, so the
        route that matters is pane signal -> window -> source."""
        main.throttle._set_cap_rate(hz)
        assert source.cap_rates[-1] == hz
        assert main.throttle.cap_hz == hz

    def test_the_pane_shows_the_rate_its_percentages_are_measured_over(self,
                                                                       main):
        from amdgraph.panes import CAP_DEFAULT, CAP_RATES
        assert main.throttle.cap_hz == CAP_RATES[CAP_DEFAULT][0]

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
        assert source.closed == 1


class TestShortcuts:
    """Freeze, Reset and Follow lost their buttons, so the key bindings are now
    the only way to reach them. That makes them load-bearing rather than a
    convenience."""

    @staticmethod
    def press_key(main, key):
        from PyQt6.QtGui import QKeySequence
        want = QKeySequence(key)
        for a in main.actions():
            if want in a.shortcuts():
                a.trigger()
                return True
        return False

    def test_space_survives_delivery_as_a_real_key(self, main):
        """trigger() proves the action is wired; it does not prove the key
        reaches it. The scroll area holds focus at startup and could plausibly
        consume Space as page-down, and Space is now the only way to freeze."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        main.show()
        app.processEvents()
        main.activateWindow()
        main.setFocus()
        app.processEvents()
        QTest.keyClick(main, Qt.Key.Key_Space)
        app.processEvents()
        assert main.view.frozen
        QTest.keyClick(main, Qt.Key.Key_Space)
        app.processEvents()
        assert not main.view.frozen

    def test_space_toggles_freeze_both_ways(self, main, source):
        assert self.press_key(main, "Space")
        assert main.view.frozen and not main.view.follow
        before = source.ticks
        main.tick()
        assert source.ticks == before + 1        # frozen view, live sampling
        assert self.press_key(main, "Space")
        assert not main.view.frozen and main.view.follow

    def test_escape_restores_following(self, main):
        main.view.zoom_to(1.0, 20.0)
        assert not main.view.follow
        assert self.press_key(main, "Esc")
        assert main.view.follow

    def test_r_resets(self, main, source):
        for _ in range(4):
            main.tick()
        assert self.press_key(main, "R")
        assert main.store.n == 0
        assert source.resets == 1

    def test_m_marks(self, main):
        main.tick()
        assert self.press_key(main, "M")
        assert main.view.markers                 # the dialog is stubbed

    @pytest.mark.parametrize("key, idx", [("[", 0), ("]", 2)])
    def test_bracket_keys_step_the_window(self, main, key, idx):
        main.cb_window.setCurrentIndex(1)
        assert self.press_key(main, key)
        assert main.cb_window.currentIndex() == idx


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

    def test_the_recording_path_is_shown_without_the_home_directory(self):
        """A screenshot of the status bar should not be mostly a username."""
        from amdgraph.window import tilde
        home = os.path.expanduser("~")
        assert tilde(f"{home}/x/y.csv") == "~/x/y.csv"
        assert tilde("/var/tmp/y.csv") == "/var/tmp/y.csv"
        assert tilde(home) == home            # not a prefix match on its own

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
