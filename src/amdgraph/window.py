"""Layer 6 -- assembly.

Builds the pane column from the catalogue, owns the sample timer and the
recorder, and wires the toolbar to the layers below. Everything here is
plumbing; if a decision about *what* to show has crept in, it belongs in
panes.py instead.

May import: everything.
"""

import os

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QComboBox, QFileDialog, QInputDialog, QLabel,
                             QMainWindow, QMessageBox, QPushButton,
                             QScrollArea, QSizePolicy, QToolBar, QVBoxLayout,
                             QWidget)

from . import render
from .axis import TimeAxis
from .chart import chart_frame
from .fields import MAX_CORE_SLOTS, THROTTLE_BITS
from .palette import INK, MUTED, SURFACE
from .panes import HEAT_AFTER_ID, PANES, THROTTLE_FIRST, available_catalogue
from .rasters import core_frame, throttle_frame
from .render import fmt_time
from .service import LocalHistoryService
from .section import SectionHeader
from .session import DATA_DIR, load_session
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
    def __init__(self, interval, open_path=None, source=None, service=None):
        """`source` is anything implementing Sampler's protocol; it defaults to
        reading this machine. Injecting it is what lets the window be built and
        driven with no hardware present, and is the seam a second platform's
        backend plugs into."""
        super().__init__()
        self.setWindowTitle("amdgraph")
        self.resize(1180, 900)
        self.interval = interval
        self.service = (service if service is not None else
                        LocalHistoryService(interval, source))
        # Compatibility aliases for frontend code and third-party sources;
        # ownership lives in the service.
        self.sampler = self.service.source
        self.store = self.service.store
        self.view = View(self.store)
        self.view.window = 300.0
        self.recorder = self.service.recorder
        self.live = True
        self._cursor_pending = False
        self.t_start = self.service.started
        # One real sample doubles as the capability inventory. Backends emit
        # owned keys with None when a reading is temporarily absent, so this
        # filters unsupported series without mistaking one missed read for an
        # unsupported sensor. It is also the one construction-time sample the
        # window has always taken; it merely moves before assembly.
        initial = self.service.last_sample
        detected_cores = initial.get("core_count")
        self.core_count = (MAX_CORE_SLOTS if detected_cores is None else
                           max(1, min(MAX_CORE_SLOTS, int(detected_cores))))
        capabilities = self.service.capabilities()
        self.catalogue, self.catalogue_groups = available_catalogue(capabilities)

        # Size the shared gutters to the text that actually has to fit, before
        # any pane is built. Fixed pixel counts clipped labels on any desktop
        # whose default font is larger than the one they were tuned against.
        render.calibrate(
            render.pane_font(),
            [n for _b, n, _f in THROTTLE_BITS]
            + [f"core {i}" for i in range(self.core_count)],
            [s.label for spec in self.catalogue for s in spec.series])

        root = QWidget()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        # A real QToolBar, for one property that matters here: when the window
        # is too narrow for every control, Qt moves the rest into an overflow
        # popup instead of refusing to shrink. The chrome had been setting the
        # window's minimum width outright -- 1108 px of it at one point -- and
        # now nothing but the charts does.
        self.toolbar = self._build_toolbar()
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        inner = QWidget()
        self.col = QVBoxLayout(inner)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(2)
        self.panes = []          # PaneFrames; each wraps a painted body
        if THROTTLE_FIRST:
            frame = throttle_frame(self.view)
            self.throttle = frame.body
            self.throttle.capRateChanged.connect(self.on_cap_rate)
            self._add_pane(frame)
        # Groups are declared by the run of titles they wrap, so the column is
        # built by walking PANES in order and opening a section when its first
        # member comes up.
        self.sections = []
        opens = {g.pane_ids[0]: g for g in self.catalogue_groups}
        grouped = {pane_id for group in self.catalogue_groups
                   for pane_id in group.pane_ids}
        header, members = None, []
        for spec in self.catalogue:
            if spec.id in opens:
                group = opens[spec.id]
                header = SectionHeader(group)
                self.col.addWidget(header)
                self.sections.append(header)
                members = []
                header.toggled.connect(
                    lambda on, m=members: self._set_section(m, on))
            frame = chart_frame(spec, self.view,
                                indent=(render.INDENT
                                        if spec.id in grouped else 0))
            self._add_pane(frame)
            if spec.id in grouped:
                members.append(frame)
                frame.setVisible(header.expanded)
            if spec.id == HEAT_AFTER_ID:
                hf = core_frame(self.view, core_count=self.core_count)
                self.heat_frame = hf
                self.heat = hf.body
                self._add_pane(hf)
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
            "QToolBar{background:#16161a;border:0;spacing:6px;"
            "padding:6px 8px;}"
            "QToolButton{background:#242429;border:1px solid #33333a;"
            "border-radius:4px;padding:3px 8px;}"
            "QToolButton:hover{background:#2d2d33;}"
            "QToolButton:checked{background:#242429;border-color:#33333a;}"
            "QCheckBox{padding:2px;}")

        self._install_shortcuts()

        notes = self.service.notes()
        if notes:
            self.status.setText("   ·   ".join(notes))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(int(interval * 1000))
        self.view.update_range()
        self.refresh()

        if open_path:
            self.open_session(open_path)

    # -- chrome -----------------------------------------------------------

    @staticmethod
    def _set_section(members, on):
        for pane in members:
            pane.setVisible(on)

    def _add_pane(self, frame):
        """Every pane is wired the same way; the base class is what makes that
        true, so adding a kind of pane means writing no plumbing here."""
        frame.body.cursorMoved.connect(self.on_cursor)
        frame.body.rangeChanged.connect(self.on_range)
        self.col.addWidget(frame)
        self.panes.append(frame)

    def _build_toolbar(self):
        bar = QToolBar("controls")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setIconSize(QSize(1, 1))          # no icons; text-only controls

        class _Adder:
            """addWidget/addSpacing, so the body below reads as it did under a
            QHBoxLayout rather than being rewritten around QAction."""

            @staticmethod
            def addWidget(w):
                bar.addWidget(w)

            @staticmethod
            def addSpacing(n):
                sp = QWidget()
                sp.setFixedWidth(n)
                bar.addWidget(sp)

            @staticmethod
            def addStretch(_n=1):
                sp = QWidget()
                sp.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Preferred)
                bar.addWidget(sp)

        h = _Adder()

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

        # Nothing in the toolbar takes focus, so Space stays bound to freeze
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
            self.service.sample_once()
            self.store = self.service.store
            self.recorder = self.service.recorder
        self.view.update_range()
        self.refresh()

    def refresh(self):
        # Only the panes actually inside the scroll viewport. Roughly half the
        # column is off-screen at any time, and repainting it is pure waste.
        for p in self.panes:
            if not p.visibleRegion().isEmpty():
                p.update_live()
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
        bits.extend(self.service.notes())
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
        self.service.reset()
        self.store = self.service.store
        self.t_start = self.service.started
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
                self.service.data_dir = DATA_DIR
                self.service.start_recording()
                self.recorder = self.service.recorder
            except OSError as e:
                QMessageBox.warning(self, "amdgraph",
                                    f"Cannot record: {e}")
                self.btn_rec.setChecked(False)
                return
            self.btn_rec.setText("■ Stop")
        else:
            self.service.stop_recording()
            self.recorder = self.service.recorder
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
        self.service.mark(label, t)
        self.view.markers = list(self.service.store.markers)
        self.refresh()

    def on_cap_rate(self, hz):
        """From the Cap reason pane's context menu."""
        self.service.set_cap_rate(hz)
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
        recorded_cores = st.latest("core_count")
        if recorded_cores is not None:
            self._set_core_count(recorded_cores)
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
        self._set_core_count(self.core_count)
        self.view.markers = []
        self.view.window = float(View.WINDOWS[1][0])
        self.cb_window.setCurrentIndex(1)
        self.view.unzoom()
        self.btn_golive.hide()
        self.setWindowTitle("amdgraph")
        self.refresh()

    def _set_core_count(self, core_count):
        """Keep the per-core body and its fixed-height wrapper in sync."""
        if not hasattr(self, "heat"):
            return
        self.heat.set_core_count(core_count)
        self.heat_frame.setFixedHeight(
            render.HEADER_H + self.heat.minimumHeight())

    def closeEvent(self, ev):
        # Qt can deliver this more than once -- an explicit close() followed by
        # the application quitting, say -- so it has to be safe to repeat.
        self.service.close()
        self.recorder = None
        super().closeEvent(ev)
