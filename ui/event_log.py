"""
ui/event_log.py — Scrollable list of lag events on the left panel.

Each row shows:
  - Severity colour indicator
  - Time of event
  - Duration
  - Cause code badge
"""
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QScrollArea,
    QFrame, QHBoxLayout, QPushButton,
)

from core.models import LagEvent

GREEN  = "#2ecc71"
AMBER  = "#f39c12"
RED    = "#e74c3c"
BG     = "#0d1117"
BG2    = "#161b22"
BG3    = "#21262d"
TEXT   = "#e6edf3"
MUTED  = "#8b949e"
ACCENT = "#58a6ff"

CAUSE_COLOURS = {
    "CPU_SPIKE":            RED,
    "RAM_EXHAUSTION":       "#9b59b6",
    "RAM_PRESSURE":         AMBER,
    "BACKGROUND_CLUSTER":   AMBER,
    "DISK_IO":              "#1abc9c",
    "SCHEDULER_CONTENTION": MUTED,
    "UNKNOWN":              MUTED,
}


def _severity_colour(score: float) -> str:
    if score < 0.5:
        return AMBER
    if score < 0.75:
        return "#e67e22"
    return RED


class EventRow(QFrame):
    """Single clickable row in the event log."""

    clicked = Signal(object)   # emits LagEvent

    def __init__(self, event: LagEvent, parent=None):
        super().__init__(parent)
        self.event = event
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()
        self._set_style(False)

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # Colour dot
        dot = QLabel("●")
        dot.setFixedWidth(14)
        colour = _severity_colour(self.event.peak_composite_score)
        dot.setStyleSheet(f"color: {colour}; font-size: 10px;")

        # Time + duration
        time_str = self.event.started_at.strftime("%H:%M:%S")
        date_str = self.event.started_at.strftime("%b %d")
        dur = round(self.event.duration_seconds, 1)

        info = QVBoxLayout()
        info.setSpacing(2)
        time_label = QLabel(f"{time_str}  <span style='color:{MUTED};font-size:10px'>{date_str}</span>")
        time_label.setTextFormat(Qt.TextFormat.RichText)
        time_label.setStyleSheet(f"color: {TEXT}; font-size: 12px; font-weight: 600;")
        dur_label = QLabel(f"{dur}s duration")
        dur_label.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
        info.addWidget(time_label)
        info.addWidget(dur_label)

        # Cause badge
        code = self.event.cause_code or "UNKNOWN"
        badge_colour = CAUSE_COLOURS.get(code, MUTED)
        badge = QLabel(code.replace("_", " "))
        badge.setStyleSheet(f"""
            color: {badge_colour};
            background: transparent;
            border: 1px solid {badge_colour};
            border-radius: 4px;
            padding: 1px 6px;
            font-size: 9px;
            font-weight: 700;
        """)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(dot)
        layout.addLayout(info, stretch=1)
        layout.addWidget(badge)

    def _set_style(self, selected: bool):
        bg = BG3 if selected else BG2
        self.setStyleSheet(f"""
            EventRow {{
                background: {bg};
                border-radius: 6px;
                border: 1px solid {'#58a6ff' if selected else '#30363d'};
            }}
            EventRow:hover {{
                background: {BG3};
                border-color: #444c56;
            }}
        """)

    def set_selected(self, val: bool):
        self._selected = val
        self._set_style(val)

    def mousePressEvent(self, event):
        self.clicked.emit(self.event)
        super().mousePressEvent(event)


class EventLogWidget(QWidget):
    """
    Left panel: scrollable list of EventRow widgets.
    Emits event_selected(LagEvent) when a row is clicked.
    """

    event_selected = Signal(object)   # LagEvent

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[EventRow] = []
        self._selected_row: EventRow | None = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        title = QLabel("LAG EVENTS")
        title.setStyleSheet(f"color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        self._count_label = QLabel("0")
        self._count_label.setStyleSheet(f"""
            color: {BG};
            background: {MUTED};
            border-radius: 8px;
            padding: 1px 7px;
            font-size: 10px;
            font-weight: 700;
        """)
        header.addWidget(title)
        header.addWidget(self._count_label)
        header.addStretch()
        layout.addLayout(header)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 4, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll, stretch=1)

        # Empty state
        self._empty_label = QLabel("No lag events yet.\nMonitoring your system…")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {MUTED}; font-size: 12px; line-height: 1.6;")
        self._list_layout.insertWidget(0, self._empty_label)

    def add_event(self, event: LagEvent):
        """Prepend a new event row at the top of the list."""
        if self._empty_label.isVisible():
            self._empty_label.hide()

        row = EventRow(event)
        row.clicked.connect(self._on_row_clicked)
        self._rows.insert(0, row)
        self._list_layout.insertWidget(0, row)

        self._count_label.setText(str(len(self._rows)))

    def _on_row_clicked(self, event: LagEvent):
        # Deselect previous
        if self._selected_row:
            self._selected_row.set_selected(False)
        # Find and select clicked row
        for row in self._rows:
            if row.event is event or row.event.id == event.id:
                row.set_selected(True)
                self._selected_row = row
                break
        self.event_selected.emit(event)
