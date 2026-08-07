"""Layer 5 -- assembly.

Builds the pane column from the catalogue, owns the sample timer and the
recorder, and wires the toolbar to the layers below. Everything here is
plumbing; if a decision about *what* to show has crept in, it belongs in
panes.py instead.

May import: everything.
"""

import os
import socket
import time
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout,
                             QInputDialog, QLabel, QMainWindow, QMessageBox,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

from . import render
from .axis import TimeAxis
from .chart import ChartPane
from .fields import N_CORES, THROTTLE_BITS
from .palette import INK, MUTED, SURFACE
from .panes import GROUPS, HEAT_AFTER, PANES, THROTTLE_FIRST
from .rasters import CorePane, ThrottlePane
from .render import fmt_time
from .sampler import Sampler
from .section import SectionHeader
from .session import DATA_DIR, Recorder, load_session, record_keys
from .store import Store
from .view import View


def tilde(path):
    """Abbreviate $HOME to ~ for display.

    The status bar shows the path being recorded to, and that path is mostly a
    username. Screenshots of this program end up in bug reports and READMEs.
    """
    home = os.path.expanduser("~")
    if path and path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


class Main(QMainWindow):
    def __init__(self, interval, open_path=None, source=None):
        """`source` is anything implementing Sampler's protocol; it defaults to
        reading this machine. Injecting it is what lets the window be built and
        driven with no hardware present, and is the seam a second platform's
        backend plugs into."""
        super().__init__()
        self.setWindowTitle("amdgraph")
        self.resize(1180, 900)
        self.interval = interval
        self.sampler = source if source is not None else Sampler()
        self.store = Store()
        self.view = View(self.store)
        self.view.window = 300.0
        self.recorder = None
        self.live = True
        self._cursor_pending = False
        self.t_start = time.monotonic()

        # Size the shared gutters to the text that actually has to fit, before
        # any pane is built. Fixed pixel counts clipped labels on any desktop
        # whose default font is larger than the one they were tuned against.
        render.calibrate(
            render.pane_font(),
            [n for _b, n, _f in THROTTLE_BITS]
            + [f"core {i}" for i in range(N_CORES)],
            [s.label for spec in PANES for s in spec.series])

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._build_toolbar())

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        self.col = QVBoxLayout(inner)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(2)
        self.panes = []
        if THROTTLE_FIRST:
            self.throttle = ThrottlePane(self.view)
            self.throttle.capRateChanged.connect(self.on_cap_rate)
            self._add_pane(self.throttle)
        # Groups are declared by the run of titles they wrap, so the column is
        # built by walking PANES in order and opening a section when its first
        # member comes up.
        self.sections = []
        opens = {g.titles[0]: g for g in GROUPS}
        grouped = {t for g in GROUPS for t in g.titles}
        header, members = None, []
        for spec in PANES:
            if spec.title in opens:
                group = opens[spec.title]
                header = SectionHeader(group)
                self.col.addWidget(header)
                self.sections.append(header)
                members = []
                header.toggled.connect(
                    lambda on, m=members: self._set_section(m, on))
            pane = ChartPane(spec, self.view)
            self._add_pane(pane)
            if spec.title in grouped:
                members.append(pane)
                pane.setVisible(header.expanded)
            if spec.title == HEAT_AFTER:
                self.heat = CorePane(self.view)
                self._add_pane(self.heat)
        if self.panes:
            self.panes[0].label_markers = True
        self.col.addStretch(1)
        self.scroll.setWidget(inner)
        lay.addWidget(self.scroll, 1)

        self.axis = TimeAxis(self.view, self.scroll)
        lay.addWidget(self.axis)
        self.status = QLabel("")
        self.status.setContentsMargins(8, 3, 8, 5)
        self.status.setStyleSheet(f"color:{MUTED.name()};")
        lay.addWidget(self.status)

        root.setStyleSheet(
            f"QWidget{{background:{SURFACE.name()};color:{INK.name()};}}"
            f"QScrollArea{{background:{SURFACE.name()};}}"
            "QPushButton{background:#242429;border:1px solid #33333a;"
            "border-radius:4px;padding:3px 10px;}"
            "QPushButton:hover{background:#2d2d33;}"
            "QPushButton:checked{background:#1c3f6b;border-color:#3987e5;}"
            "QComboBox{background:#242429;border:1px solid #33333a;"
            "border-radius:4px;padding:2px 6px;}"
            "QCheckBox{padding:2px;}")

        self._install_shortcuts()

        notes = self.sampler.notes()
        if notes:
            self.status.setText("   ·   ".join(notes))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(int(interval * 1000))
        self.tick()

        if open_path:
            self.open_session(open_path)

    # -- chrome -----------------------------------------------------------

    @staticmethod
    def _set_section(members, on):
        for pane in members:
            pane.setVisible(on)

    def _add_pane(self, pane):
        """Every pane is wired the same way; the base class is what makes that
        true, so adding a kind of pane means writing no plumbing here."""
        pane.cursorMoved.connect(self.on_cursor)
        pane.rangeChanged.connect(self.on_range)
        self.col.addWidget(pane)
        self.panes.append(pane)

    def _build_toolbar(self):
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(6)

        # Freeze, Reset and Follow used to have buttons here. Each duplicated a
        # single-key shortcut, and between them they were 174 px of a toolbar
        # that set the whole window's minimum width. Space is a guessable
        # binding for pause, `r` for reset, and Follow was never really a
        # control -- dragging or zooming turns it off by itself and the status
        # bar already says "Esc to follow again" when it is off. Mark stays,
        # because `m` is not guessable and the feature exists precisely for the
        # things no sensor can see.
        self.btn_mark = QPushButton("Mark…")
        self.btn_mark.setToolTip(
            "Drop a labelled marker at the current time (key: m). For the "
            "things no sensor sees — flipping the laptop, moving it off your "
            "lap, changing a limit by hand. Saved into the recording.")
        self.btn_mark.clicked.connect(self.on_mark)
        h.addWidget(self.btn_mark)

        h.addSpacing(10)
        h.addWidget(QLabel("Window"))
        self.cb_window = QComboBox()
        for _, lbl in View.WINDOWS:
            self.cb_window.addItem(lbl)
        self.cb_window.setCurrentIndex(1)
        self.cb_window.currentIndexChanged.connect(self.on_window)
        h.addWidget(self.cb_window)

        # Cap poll moved to a right-click on the Cap reason pane, which is the
        # only thing it affects and where the rate is now printed -- the duty
        # cycles in that header are meaningless without knowing it. It was a
        # set-once expert control occupying 110 px of permanent chrome.

        # The per-core metric selector went the same way as Cap poll: onto the
        # pane it governs, which sits most of a screen below this toolbar and
        # already names the current mode in its own header.

        h.addStretch(1)

        self.btn_rec = QPushButton("● Record")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setToolTip(f"Append samples to {tilde(DATA_DIR)}")
        self.btn_rec.toggled.connect(self.on_record)
        h.addWidget(self.btn_rec)

        # Load and clear are mutually exclusive -- there is never a moment when
        # both apply -- so they are one button that says which one it is,
        # rather than two with one of them greyed out.
        self.btn_overlay = QPushButton("Overlay…")
        self.btn_overlay.setToolTip(
            "Load a recording and draw it as a ghost behind the live trace, "
            "aligned by elapsed time")
        self.btn_overlay.clicked.connect(self.on_overlay_button)
        h.addWidget(self.btn_overlay)

        b = QPushButton("Open…")
        b.setToolTip("Stop sampling and browse a recorded session")
        b.clicked.connect(lambda: self.on_open())
        h.addWidget(b)

        # Hidden while live: the action does not exist yet, and a permanently
        # greyed-out button is chrome that never earns its width.
        self.btn_golive = QPushButton("Go live")
        self.btn_golive.clicked.connect(self.go_live)
        self.btn_golive.hide()
        h.addWidget(self.btn_golive)

        # Nothing in the toolbar takes focus, so Space stays bound to Freeze
        # rather than re-triggering whichever button was clicked last.
        for w in bar.findChildren(QWidget):
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return bar

    def _install_shortcuts(self):
        def add(keys, fn):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(fn)
            self.addAction(a)

        add(["Space"], lambda: self.on_pause(not self.view.frozen))
        add(["R"], self.on_reset)
        add(["M"], self.on_mark)
        add(["Esc"], lambda: self.on_follow(True))
        add(["Q", "Ctrl+Q"], self.close)
        add(["["], lambda: self.cb_window.setCurrentIndex(
            max(0, self.cb_window.currentIndex() - 1)))
        add(["]"], lambda: self.cb_window.setCurrentIndex(
            min(len(View.WINDOWS) - 1, self.cb_window.currentIndex() + 1)))

    # -- sampling ---------------------------------------------------------

    def tick(self):
        # Sampling never stops while live -- "freeze" only holds the view
        # still. History keeps filling in behind you, so releasing the freeze
        # shows what happened while you were reading, not a gap.
        if self.live:
            t = time.monotonic() - self.t_start
            s = self.sampler.sample()
            self.store.append(t, s)
            if self.recorder:
                self.recorder.write(t, s)
        self.view.update_range()
        self.refresh()

    def refresh(self):
        # Only the panes actually inside the scroll viewport. Roughly half the
        # column is off-screen at any time, and repainting it is pure waste.
        for p in self.panes:
            if not p.visibleRegion().isEmpty():
                p.update()
        self.axis.update()
        self.update_status()

    def update_status(self):
        bits = []
        if not self.live:
            path = getattr(self, "session_path", None)
            bits.append(f"viewing {os.path.basename(path)}" if path
                        else "viewing session")
        elif self.view.frozen:
            bits.append(f"FROZEN · still sampling at {self.interval:g}s")
        else:
            bits.append(f"live · {self.interval:g}s")
        bits.append(f"{self.view.store.n} samples")
        span = self.view.store.span()
        bits.append(f"span {fmt_time(span[1] - span[0])}")
        if not self.view.follow:
            bits.append(f"showing {fmt_time(self.view.t1 - self.view.t0)}"
                        " · Esc to follow again")
        if self.recorder:
            bits.append(f"recording → {tilde(self.recorder.path)}")
        if self.view.overlay is not None:
            bits.append(f"overlay: {self.view.overlay_name}")
        bits.extend(self.sampler.notes())
        self.status.setText("   ·   ".join(bits))

    # -- handlers ---------------------------------------------------------

    def on_cursor(self, t):
        # Mouse-move events arrive far faster than the eye can use. Coalesce
        # them onto a ~30 Hz timer, or sweeping the pointer across the window
        # repaints every pane per event and burns a core doing it.
        self.view.cursor = t
        if not self._cursor_pending:
            self._cursor_pending = True
            QTimer.singleShot(33, self._flush_cursor)

    def _flush_cursor(self):
        self._cursor_pending = False
        self.refresh()

    def on_range(self):
        # Follow state is reported by the status bar, not by a button. A drag
        # or a wheel turns it off; Esc turns it back on.
        self.refresh()

    def on_pause(self, on):
        self.view.frozen = on
        self.view.follow = not on
        self.refresh()

    def on_reset(self):
        """Discard live history. Harmless while browsing a recording -- the
        live buffer is a separate store from the one being viewed."""
        self.store = Store()
        self.t_start = time.monotonic()
        self.sampler.reset()
        if self.live:
            self.view.store = self.store
            self.view.markers = []
            self.view.unzoom()
        self.refresh()

    def on_window(self, i):
        self.view.window = float(View.WINDOWS[i][0])
        self.view.follow = True
        self.view.update_range()
        self.refresh()

    def on_follow(self, on):
        self.view.follow = on
        if on:
            self.view.update_range()
        self.refresh()

    def on_record(self, on):
        if on:
            try:
                os.makedirs(DATA_DIR, exist_ok=True)
                name = datetime.now().strftime("%Y%m%d-%H%M%S") + ".csv"
                path = os.path.join(DATA_DIR, name)
                meta = {
                    "amdgraph": "session v1",
                    "started": datetime.now().astimezone().isoformat(),
                    "host": socket.gethostname(),
                    "interval": f"{self.interval:g}",
                    **self.sampler.meta(),
                }
                self.recorder = Recorder(path, record_keys(), meta)
            except OSError as e:
                QMessageBox.warning(self, "amdgraph",
                                    f"Cannot record: {e}")
                self.btn_rec.setChecked(False)
                return
            self.btn_rec.setText("■ Stop")
        else:
            if self.recorder:
                self.recorder.close()
            self.recorder = None
            self.btn_rec.setText("● Record")
        self.refresh()

    def _pick(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self, "Open amdgraph session", DATA_DIR, "CSV (*.csv);;All (*)")
        return path

    def on_overlay_button(self):
        """One button, two states: load a ghost, or drop the one that is up."""
        if self.view.overlay is not None:
            self.on_clear_overlay()
        else:
            self.on_overlay()

    def on_overlay(self):
        path = self._pick()
        if not path:
            return
        try:
            st = load_session(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "amdgraph", f"Cannot load: {e}")
            return
        self.view.overlay = st
        self.view.overlay_name = os.path.basename(path)
        self.btn_overlay.setText("Clear overlay")
        self.refresh()

    def on_mark(self):
        """Place a marker at the newest sample, not at the wall clock: the
        marker has to land on the same axis as the data it explains."""
        span = self.view.store.span()
        t = span[1] if self.view.store.n else 0.0
        text, ok = QInputDialog.getText(self, "amdgraph", "Marker label:")
        if not ok:
            return
        label = (text or "").strip() or "mark"
        self.view.markers.append((t, label))
        if self.recorder:
            self.recorder.mark(t, label)
        self.refresh()

    def on_cap_rate(self, hz):
        """From the Cap reason pane's context menu."""
        self.sampler.set_cap_rate(hz)
        self.refresh()

    def on_clear_overlay(self):
        self.view.overlay = None
        self.view.overlay_name = ""
        self.btn_overlay.setText("Overlay…")
        self.refresh()

    def on_open(self, path=None):
        path = path or self._pick()
        if not path:
            return
        self.open_session(path)

    def open_session(self, path):
        try:
            st = load_session(path)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "amdgraph", f"Cannot load: {e}")
            return
        self.live = False
        self.session_path = path
        self.view.store = st          # self.store stays the live buffer
        self.view.markers = list(st.markers)
        self.view.follow = True
        self.view.window = 0.0
        self.cb_window.setCurrentIndex(len(View.WINDOWS) - 1)
        self.view.update_range()
        self.btn_golive.show()
        self.setWindowTitle(f"amdgraph — {os.path.basename(path)}")
        self.refresh()

    def go_live(self):
        self.live = True
        self.session_path = None
        self.view.store = self.store
        self.view.markers = []
        self.view.window = float(View.WINDOWS[1][0])
        self.cb_window.setCurrentIndex(1)
        self.view.unzoom()
        self.btn_golive.hide()
        self.setWindowTitle("amdgraph")
        self.refresh()

    def closeEvent(self, ev):
        # Qt can deliver this more than once -- an explicit close() followed by
        # the application quitting, say -- so it has to be safe to repeat.
        if self.recorder:
            self.recorder.close()
            self.recorder = None
        self.sampler.close()
        super().closeEvent(ev)
