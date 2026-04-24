"""
ui/main_window.py — Main application window.

Layout:
  ┌──────────────────────────────────────────────────────┐
  │  Header: app name + status indicator                 │
  ├──────────────────────────────────────────────────────┤
  │  Live metrics bar (CPU / RAM / Responsiveness)       │
  ├────────────────────┬─────────────────────────────────┤
  │  Event log         │  Detail panel                  │
  │  (scrollable list) │  (shown when event selected)   │
  └────────────────────┴─────────────────────────────────┘
"""
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont, QColor, QPalette
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSplitter, QFrame, QProgressBar, QStatusBar,
    QSystemTrayIcon, QMenu, QApplication,
)
from PySide6.QtGui import QIcon, QAction

from core.models import SystemSample, LagScore, LagEvent, LagSnapshot
from ui.event_log import EventLogWidget
from ui.detail_panel import DetailPanelWidget


# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------

GREEN = "#2ecc71"
AMBER = "#f39c12"
RED   = "#e74c3c"
BG    = "#0d1117"
BG2   = "#161b22"
TEXT  = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#58a6ff"


def severity_colour(composite: float) -> str:
    if composite < 0.4:
        return GREEN
    if composite < 0.7:
        return AMBER
    return RED


# ---------------------------------------------------------------------------
# Live metric widget
# ---------------------------------------------------------------------------

class MetricBar(QFrame):
    """One labelled metric with a coloured progress bar."""

    def __init__(self, label: str, unit: str = "%", parent=None):
        super().__init__(parent)
        self.unit = unit
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {MUTED}; font-size: 11px; font-weight: 600;")

        self._value = QLabel("—")
        self._value.setStyleSheet(f"color: {TEXT}; font-size: 22px; font-weight: 700;")

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)
        self._bar.setStyleSheet(f"""
            QProgressBar {{ background: #30363d; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
        """)

        layout.addWidget(self._label)
        layout.addWidget(self._value)
        layout.addWidget(self._bar)

        self.setStyleSheet(f"background: {BG2}; border-radius: 8px;")

    def update_value(self, value: float, colour: str | None = None):
        display = f"{value:.0f}{self.unit}" if self.unit != "ms" else f"{value:.1f} ms"
        self._value.setText(display)
        pct = min(int(value), 100)
        self._bar.setValue(pct)
        c = colour or ACCENT
        self._bar.setStyleSheet(f"""
            QProgressBar {{ background: #30363d; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {c}; border-radius: 2px; }}
        """)
        self._value.setStyleSheet(f"color: {c}; font-size: 22px; font-weight: 700;")


# ---------------------------------------------------------------------------
# Status indicator dot
# ---------------------------------------------------------------------------

class StatusDot(QLabel):
    def __init__(self, parent=None):
        super().__init__("●  MONITORING", parent)
        self.set_ok()

    def set_ok(self):
        self.setStyleSheet(f"color: {GREEN}; font-size: 12px; font-weight: 700; letter-spacing: 1px;")
        self.setText("●  MONITORING")

    def set_warning(self):
        self.setStyleSheet(f"color: {AMBER}; font-size: 12px; font-weight: 700; letter-spacing: 1px;")
        self.setText("●  ELEVATED")

    def set_lag(self):
        self.setStyleSheet(f"color: {RED}; font-size: 12px; font-weight: 700; letter-spacing: 1px;")
        self.setText("●  LAG DETECTED")

    def set_learning(self):
        self.setStyleSheet(f"color: {MUTED}; font-size: 12px; font-weight: 700; letter-spacing: 1px;")
        self.setText("●  LEARNING BASELINE…")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):

    def __init__(self, collector, engine, recorder, analyzer, storage, parent=None):
        super().__init__(parent)
        self._collector = collector
        self._engine = engine
        self._recorder = recorder
        self._analyzer = analyzer
        self._storage = storage

        self._active_event: LagEvent | None = None

        self.setWindowTitle("LagLense")
        self.resize(1100, 720)
        self.setMinimumSize(800, 550)
        self._apply_dark_theme()
        self._build_ui()
        self._connect_signals()
        self._setup_tray()
        self._load_history()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # --- Header ---
        header = QHBoxLayout()
        title = QLabel("LagLense")
        title.setStyleSheet(f"color: {TEXT}; font-size: 20px; font-weight: 800;")
        self._status_dot = StatusDot()
        self._baseline_label = QLabel("Baseline: learning…")
        self._baseline_label.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self._baseline_label)
        header.addSpacing(16)
        header.addWidget(self._status_dot)
        root.addLayout(header)

        # --- Metrics bar ---
        metrics_row = QHBoxLayout()
        self._cpu_bar = MetricBar("CPU")
        self._ram_bar = MetricBar("RAM")
        self._resp_bar = MetricBar("RESPONSIVENESS", unit="ms")
        self._score_bar = MetricBar("LAG SCORE", unit="%")
        for w in (self._cpu_bar, self._ram_bar, self._resp_bar, self._score_bar):
            metrics_row.addWidget(w)
        root.addLayout(metrics_row)

        # --- Splitter: event log | detail panel ---
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet("QSplitter::handle { background: #30363d; }")

        self._event_log = EventLogWidget()
        self._detail_panel = DetailPanelWidget()

        splitter.addWidget(self._event_log)
        splitter.addWidget(self._detail_panel)
        splitter.setSizes([380, 680])
        root.addWidget(splitter, stretch=1)

        # --- Status bar ---
        sb = QStatusBar()
        sb.setStyleSheet(f"color: {MUTED}; font-size: 11px; background: {BG};")
        self._event_count_label = QLabel("0 events recorded")
        sb.addPermanentWidget(self._event_count_label)
        self.setStatusBar(sb)
        sb.showMessage("Collecting system data…")

    # ------------------------------------------------------------------
    # Signals
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self._collector.sample_ready.connect(self._on_sample)
        self._engine.score_updated.connect(self._on_score)
        self._engine.lag_started.connect(self._on_lag_started)
        self._engine.lag_ended.connect(self._on_lag_ended)
        self._engine.baseline_updated.connect(self._on_baseline_updated)
        self._event_log.event_selected.connect(self._on_event_selected)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @Slot(object)
    def _on_sample(self, sample: SystemSample):
        score_obj = self._engine.recent_scores[-1] if self._engine.recent_scores else None
        composite = score_obj.composite if score_obj else 0.0
        self._recorder.record_sample(sample, composite)
        self._engine.ingest(sample)

    @Slot(object)
    def _on_score(self, score: LagScore):
        c_cpu = severity_colour(score.cpu_score)
        c_ram = severity_colour(score.ram_score)
        c_resp = severity_colour(score.responsiveness_score)
        c_composite = severity_colour(score.composite)

        # Get last sample for actual values
        samples = self._engine.recent_samples
        if samples:
            last = samples[-1]
            self._cpu_bar.update_value(last.cpu_percent, c_cpu)
            self._ram_bar.update_value(last.ram_percent, c_ram)
            self._resp_bar.update_value(last.responsiveness_ms, c_resp)

        self._score_bar.update_value(score.composite * 100, c_composite)

        # Update status dot
        if score.composite >= 0.6:
            self._status_dot.set_lag()
        elif score.composite >= 0.35:
            self._status_dot.set_warning()
        else:
            if not self._engine.baseline.is_ready:
                self._status_dot.set_learning()
            else:
                self._status_dot.set_ok()

    @Slot(object)
    def _on_lag_started(self, started_at: datetime):
        self._active_event = LagEvent(
            id=None,
            started_at=started_at,
            ended_at=None,
            peak_composite_score=0.0,
            cause="",
            cause_code="",
        )
        self.statusBar().showMessage(f"⚠  Lag event started at {started_at.strftime('%H:%M:%S')}")

    @Slot(object, float)
    def _on_lag_ended(self, ended_at: datetime, peak_score: float):
        if self._active_event is None:
            return

        event = self._active_event
        event.ended_at = ended_at
        event.peak_composite_score = peak_score
        event.duration_seconds = (ended_at - event.started_at).total_seconds()

        # Capture snapshot
        snapshot = self._recorder.capture(event)

        # Analyse cause
        cause_code, cause = self._analyzer.analyze(
            snapshot.peak_sample, snapshot.pre_lag_samples
        )
        event.cause = cause
        event.cause_code = cause_code

        # Persist
        event_id = self._storage.save_event(event)
        event.id = event_id
        snapshot.event_id = event_id
        self._storage.save_snapshot(snapshot)

        # Update UI
        self._event_log.add_event(event)
        count = self._storage.event_count()
        self._event_count_label.setText(f"{count} event{'s' if count != 1 else ''} recorded")
        self.statusBar().showMessage(
            f"✓  Lag event ended — {round(event.duration_seconds, 1)}s — {cause_code}"
        )

        # Tray notification
        if self._tray and self._tray.isVisible():
            self._tray.showMessage(
                "Lag Event Detected",
                f"{cause_code}: {cause[:80]}…" if len(cause) > 80 else cause,
                QSystemTrayIcon.MessageIcon.Warning,
                4000,
            )

        self._active_event = None

    @Slot(object)
    def _on_baseline_updated(self, baseline):
        if baseline.is_ready:
            self._baseline_label.setText(
                f"Baseline: CPU {baseline.cpu_mean:.0f}% ± {baseline.cpu_std:.0f}  |  "
                f"RAM {baseline.ram_mean:.0f}% ± {baseline.ram_std:.0f}"
            )
        else:
            remaining = max(0, 60 - baseline.sample_count)
            self._baseline_label.setText(f"Baseline: learning… ({remaining}s remaining)")

    @Slot(object)
    def _on_event_selected(self, event: LagEvent):
        snapshot = self._storage.get_snapshot_for_event(event.id)
        self._detail_panel.show_event(event, snapshot)

    # ------------------------------------------------------------------
    # History load
    # ------------------------------------------------------------------

    def _load_history(self):
        events = self._storage.get_recent_events(limit=200)
        for e in reversed(events):
            self._event_log.add_event(e)
        count = self._storage.event_count()
        self._event_count_label.setText(f"{count} event{'s' if count != 1 else ''} recorded")

    # ------------------------------------------------------------------
    # Tray
    # ------------------------------------------------------------------

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.show()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _apply_dark_theme(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {BG};
                color: {TEXT};
                font-family: 'Segoe UI', 'SF Pro Display', system-ui, sans-serif;
                font-size: 13px;
            }}
            QSplitter {{ background: {BG}; }}
            QScrollBar:vertical {{
                background: {BG2}; width: 8px; border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #30363d; border-radius: 4px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    def closeEvent(self, event):
        """Minimise to tray instead of quitting."""
        event.ignore()
        self.hide()
        self._tray.showMessage(
            "System Lag Detective",
            "Still running in the background.",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )
