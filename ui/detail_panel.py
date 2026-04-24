"""
ui/detail_panel.py — Right panel shown when a lag event is selected.

Shows:
  - Cause explanation (large, human-readable)
  - Peak metrics (CPU / RAM / Responsiveness)
  - Pre-lag timeline (ASCII sparkline + values)
  - Top offending processes table
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QScrollArea, QGridLayout,
)

from core.models import LagEvent, LagSnapshot

GREEN  = "#2ecc71"
AMBER  = "#f39c12"
RED    = "#e74c3c"
BG     = "#0d1117"
BG2    = "#161b22"
BG3    = "#21262d"
TEXT   = "#e6edf3"
MUTED  = "#8b949e"
ACCENT = "#58a6ff"
PURPLE = "#9b59b6"

CAUSE_ICONS = {
    "CPU_SPIKE":            "🔥",
    "RAM_EXHAUSTION":       "💾",
    "RAM_PRESSURE":         "⚠️",
    "BACKGROUND_CLUSTER":   "🐝",
    "DISK_IO":              "💿",
    "SCHEDULER_CONTENTION": "⚙️",
    "UNKNOWN":              "❓",
}

CAUSE_COLOURS = {
    "CPU_SPIKE":            RED,
    "RAM_EXHAUSTION":       PURPLE,
    "RAM_PRESSURE":         AMBER,
    "BACKGROUND_CLUSTER":   AMBER,
    "DISK_IO":              "#1abc9c",
    "SCHEDULER_CONTENTION": MUTED,
    "UNKNOWN":              MUTED,
}


def _sparkline(values: list[float], width: int = 20) -> str:
    """Generate a Unicode block sparkline from a list of floats."""
    if not values:
        return "─" * width
    chars = " ▁▂▃▄▅▆▇█"
    mn, mx = min(values), max(values)
    span = mx - mn or 1
    result = ""
    for v in values[-width:]:
        idx = int((v - mn) / span * (len(chars) - 1))
        result += chars[idx]
    return result


class SectionHeader(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(f"""
            color: {MUTED};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 1.5px;
            padding-bottom: 4px;
            border-bottom: 1px solid #30363d;
        """)


class MetricChip(QFrame):
    """Small labelled value chip."""
    def __init__(self, label: str, value: str, colour: str = TEXT, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {MUTED}; font-size: 10px; font-weight: 600;")
        val = QLabel(value)
        val.setStyleSheet(f"color: {colour}; font-size: 18px; font-weight: 700;")
        layout.addWidget(lbl)
        layout.addWidget(val)
        self.setStyleSheet(f"background: {BG3}; border-radius: 6px;")


class DetailPanelWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_empty()

    def _build_empty(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 0, 0, 0)
        placeholder = QLabel("← Select a lag event\nto see the full diagnosis")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet(f"color: {MUTED}; font-size: 14px; line-height: 1.8;")
        layout.addWidget(placeholder)
        self._layout = layout

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_event(self, event: LagEvent, snapshot: LagSnapshot | None):
        self._clear()
        self._layout.setContentsMargins(16, 0, 0, 0)
        self._layout.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 12, 16)
        cl.setSpacing(16)

        # ── Cause header ──────────────────────────────────────────────
        code = event.cause_code or "UNKNOWN"
        icon = CAUSE_ICONS.get(code, "❓")
        colour = CAUSE_COLOURS.get(code, MUTED)

        cause_frame = QFrame()
        cause_frame.setStyleSheet(f"""
            background: {BG2};
            border-left: 3px solid {colour};
            border-radius: 6px;
        """)
        cf_layout = QVBoxLayout(cause_frame)
        cf_layout.setContentsMargins(16, 14, 16, 14)
        cf_layout.setSpacing(6)

        code_label = QLabel(f"{icon}  {code.replace('_', ' ')}")
        code_label.setStyleSheet(f"color: {colour}; font-size: 13px; font-weight: 700;")

        time_str = event.started_at.strftime("%A, %b %d at %H:%M:%S")
        dur = round(event.duration_seconds, 1)
        meta_label = QLabel(f"{time_str}  ·  {dur}s")
        meta_label.setStyleSheet(f"color: {MUTED}; font-size: 11px;")

        explanation = QLabel(event.cause or "No explanation available.")
        explanation.setWordWrap(True)
        explanation.setStyleSheet(f"color: {TEXT}; font-size: 12px; line-height: 1.6;")

        cf_layout.addWidget(code_label)
        cf_layout.addWidget(meta_label)
        cf_layout.addWidget(explanation)
        cl.addWidget(cause_frame)

        # ── Peak metrics ──────────────────────────────────────────────
        if snapshot:
            cl.addWidget(SectionHeader("Peak Metrics"))
            chips_row = QHBoxLayout()
            cpu_c = RED if snapshot.peak_cpu > 80 else AMBER if snapshot.peak_cpu > 60 else GREEN
            ram_c = RED if snapshot.peak_ram > 88 else AMBER if snapshot.peak_ram > 70 else GREEN
            resp_c = RED if snapshot.peak_responsiveness_ms > 50 else AMBER if snapshot.peak_responsiveness_ms > 20 else GREEN
            score_c = RED if event.peak_composite_score > 0.75 else AMBER

            chips_row.addWidget(MetricChip("CPU", f"{snapshot.peak_cpu:.0f}%", cpu_c))
            chips_row.addWidget(MetricChip("RAM", f"{snapshot.peak_ram:.0f}%", ram_c))
            chips_row.addWidget(MetricChip("RESPONSE", f"{snapshot.peak_responsiveness_ms:.1f}ms", resp_c))
            chips_row.addWidget(MetricChip("SCORE", f"{event.peak_composite_score*100:.0f}%", score_c))
            chips_row.addStretch()
            cl.addLayout(chips_row)

            # ── Pre-lag timeline ──────────────────────────────────────
            if snapshot.pre_lag_samples:
                cl.addWidget(SectionHeader("Pre-Lag Timeline (last 5s)"))
                timeline_frame = QFrame()
                timeline_frame.setStyleSheet(f"background: {BG2}; border-radius: 6px;")
                tl = QGridLayout(timeline_frame)
                tl.setContentsMargins(14, 12, 14, 12)
                tl.setSpacing(6)

                samples = snapshot.pre_lag_samples
                cpu_vals  = [s.cpu_percent for s in samples]
                ram_vals  = [s.ram_percent for s in samples]
                resp_vals = [s.responsiveness_ms for s in samples]

                rows = [
                    ("CPU",    cpu_vals,  "%",  RED),
                    ("RAM",    ram_vals,  "%",  PURPLE),
                    ("RESP",   resp_vals, "ms", ACCENT),
                ]
                for i, (label, vals, unit, c) in enumerate(rows):
                    lbl = QLabel(label)
                    lbl.setStyleSheet(f"color: {MUTED}; font-size: 10px; font-weight: 700;")
                    spark = QLabel(_sparkline(vals, width=16))
                    spark.setStyleSheet(f"color: {c}; font-family: monospace; font-size: 14px; letter-spacing: 2px;")
                    peak_lbl = QLabel(f"{max(vals):.0f}{unit}")
                    peak_lbl.setStyleSheet(f"color: {c}; font-size: 11px; font-weight: 600;")
                    tl.addWidget(lbl,      i, 0)
                    tl.addWidget(spark,    i, 1)
                    tl.addWidget(peak_lbl, i, 2)

                cl.addWidget(timeline_frame)

            # ── Top processes ─────────────────────────────────────────
            if snapshot.top_processes:
                cl.addWidget(SectionHeader("Top Processes at Peak"))
                proc_frame = QFrame()
                proc_frame.setStyleSheet(f"background: {BG2}; border-radius: 6px;")
                pl = QVBoxLayout(proc_frame)
                pl.setContentsMargins(14, 12, 14, 12)
                pl.setSpacing(4)

                # Header row
                hdr = QHBoxLayout()
                for txt, stretch in [("PROCESS", 3), ("PID", 1), ("CPU", 1), ("RAM", 1)]:
                    l = QLabel(txt)
                    l.setStyleSheet(f"color: {MUTED}; font-size: 9px; font-weight: 700; letter-spacing: 1px;")
                    hdr.addWidget(l, stretch=stretch)
                pl.addLayout(hdr)

                div = QFrame()
                div.setFrameShape(QFrame.Shape.HLine)
                div.setStyleSheet("color: #30363d;")
                pl.addWidget(div)

                for proc in snapshot.top_processes[:8]:
                    row = QHBoxLayout()
                    cpu_c = RED if proc.cpu_percent > 50 else AMBER if proc.cpu_percent > 20 else TEXT

                    name_l = QLabel(proc.name[:28])
                    name_l.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
                    pid_l = QLabel(str(proc.pid))
                    pid_l.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
                    cpu_l = QLabel(f"{proc.cpu_percent:.1f}%")
                    cpu_l.setStyleSheet(f"color: {cpu_c}; font-size: 11px; font-weight: 600;")
                    mem_l = QLabel(f"{proc.memory_mb:.0f} MB")
                    mem_l.setStyleSheet(f"color: {MUTED}; font-size: 11px;")

                    row.addWidget(name_l, stretch=3)
                    row.addWidget(pid_l,  stretch=1)
                    row.addWidget(cpu_l,  stretch=1)
                    row.addWidget(mem_l,  stretch=1)
                    pl.addLayout(row)

                cl.addWidget(proc_frame)

        cl.addStretch()
        scroll.setWidget(content)
        self._layout.addWidget(scroll)
