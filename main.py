"""
main.py — Application entry point.

Wires together:
  - SystemCollector (background thread)
  - DetectionEngine
  - SnapshotRecorder
  - CauseAnalyzer
  - Storage
  - MainWindow (UI)

Everything communicates via Qt signals/slots — no shared state, no locks.
"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.collectors import SystemCollector
from core.detection import DetectionEngine
from core.recorder import SnapshotRecorder
from core.analyzer import CauseAnalyzer
from core.storage import Storage
from ui.main_window import MainWindow


def main():
    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("System Lag Detective")
    app.setApplicationVersion("1.0.0")
    app.setQuitOnLastWindowClosed(False)  # Keep running in tray

    # --- Instantiate core components ---
    collector = SystemCollector(interval=1.0, top_n_processes=10)
    engine    = DetectionEngine()
    recorder  = SnapshotRecorder(pre_lag_seconds=5)
    analyzer  = CauseAnalyzer()
    storage   = Storage()

    # --- Build UI ---
    window = MainWindow(
        collector=collector,
        engine=engine,
        recorder=recorder,
        analyzer=analyzer,
        storage=storage,
    )
    window.show()

    # --- Start background collection ---
    collector.start()

    exit_code = app.exec()
    collector.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
