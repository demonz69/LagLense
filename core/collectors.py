"""
core/collectors.py — Background QThread collectors for CPU, RAM, Processes, Responsiveness.

Each collector runs in its own thread and emits a signal every second.
The UI and detection engine connect to these signals — fully decoupled.
"""
import time
import statistics
from datetime import datetime

import psutil
from PySide6.QtCore import QThread, Signal

from core.models import SystemSample, ProcessSample


# ---------------------------------------------------------------------------
# Responsiveness probe
# ---------------------------------------------------------------------------

def measure_responsiveness_ms() -> float:
    """
    Measure how long a trivial OS operation takes (in milliseconds).

    A healthy system completes this in < 5 ms.
    A stressed system (paging, scheduler contention) may take 50–500 ms.

    We use time.sleep(0.001) accuracy as a proxy: we ask for 1 ms sleep and
    measure how long it actually takes.  Repeated 5 times; we return the median.
    """
    samples = []
    for _ in range(5):
        t0 = time.perf_counter()
        time.sleep(0.001)   # 1 ms
        elapsed_ms = (time.perf_counter() - t0) * 1000
        samples.append(elapsed_ms)
    return statistics.median(samples)


# ---------------------------------------------------------------------------
# Main collector thread
# ---------------------------------------------------------------------------

class SystemCollector(QThread):
    """
    Collects all system metrics every `interval` seconds.
    Emits `sample_ready` with a filled SystemSample dataclass.

    Why one thread instead of four separate ones?
    → Fewer synchronisation headaches; all metrics share the same timestamp.
    """

    sample_ready = Signal(object)   # emits SystemSample
    error_occurred = Signal(str)

    def __init__(self, interval: float = 1.0, top_n_processes: int = 10, parent=None):
        super().__init__(parent)
        self.interval = interval
        self.top_n = top_n_processes
        self._running = False

        # Prime psutil CPU counters so first call isn't 0.0
        psutil.cpu_percent(interval=None)
        for proc in psutil.process_iter():
            try:
                proc.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    # ------------------------------------------------------------------
    def run(self):
        self._running = True
        while self._running:
            loop_start = time.perf_counter()
            try:
                sample = self._collect()
                self.sample_ready.emit(sample)
            except Exception as exc:  # noqa: BLE001
                self.error_occurred.emit(str(exc))

            # Sleep for the remainder of the interval
            elapsed = time.perf_counter() - loop_start
            remaining = self.interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    def stop(self):
        self._running = False
        self.wait(2000)

    # ------------------------------------------------------------------
    def _collect(self) -> SystemSample:
        now = datetime.now()

        # --- CPU ---
        cpu_overall = psutil.cpu_percent(interval=None)
        cpu_cores = psutil.cpu_percent(interval=None, percpu=True)

        # --- Memory ---
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()

        # --- Responsiveness probe ---
        responsiveness = measure_responsiveness_ms()

        # --- Top processes ---
        processes = self._top_processes()

        return SystemSample(
            timestamp=now,
            cpu_percent=cpu_overall,
            cpu_per_core=cpu_cores,
            ram_percent=vm.percent,
            ram_used_mb=vm.used / (1024 ** 2),
            ram_total_mb=vm.total / (1024 ** 2),
            swap_percent=swap.percent,
            responsiveness_ms=responsiveness,
            top_processes=processes,
        )

    def _top_processes(self) -> list[ProcessSample]:
        procs = []
        for proc in psutil.process_iter(
            ["pid", "name", "cpu_percent", "memory_info", "status"]
        ):
            try:
                info = proc.info
                mem_mb = (info["memory_info"].rss / (1024 ** 2)) if info["memory_info"] else 0.0
                procs.append(ProcessSample(
                    pid=info["pid"],
                    name=info["name"] or "unknown",
                    cpu_percent=info["cpu_percent"] or 0.0,
                    memory_mb=mem_mb,
                    status=info["status"] or "unknown",
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by CPU first, then RAM as tiebreaker
        procs.sort(key=lambda p: (p.cpu_percent, p.memory_mb), reverse=True)
        return procs[: self.top_n]
