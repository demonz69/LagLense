# 🔍 LagLens v1.0

> **See exactly why your PC lagged — with forensic context captured before the spike hit.**

LagLens is a Windows desktop tool that monitors your system in real time and automatically diagnoses PC lag. Unlike Task Manager, which only shows you what's happening *right now*, LagLens captures the **5 seconds before** a lag event fires and tells you in plain English what caused it.

---

## 🚀 For Windows Users (No Python Needed)

**Download `LagLens.exe` from the [Releases](../../releases) page and run it. That's it.**

- No installation required
- No Python required
- Double-click and it starts monitoring immediately
- Minimises to the system tray when closed

---

## 🐧 For Linux / macOS Users (From Source)

```bash
git clone https://github.com/YOUR_USERNAME/laglens.git
cd laglens
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

**Requirements:** Python 3.10+

---

## ✨ What It Does

### Live Dashboard
| Metric | What it measures |
|---|---|
| CPU % | Overall processor usage |
| RAM % | Memory used vs total, swap pressure |
| Responsiveness | How long a trivial OS operation takes (ms) — catches disk-bound lag that CPU% misses |
| Lag Score | Composite 0–100% health indicator |

Status dot colour: 🟢 OK → 🟡 Elevated → 🔴 Lag detected

### Smart Detection
- Learns *your* machine's normal behaviour in ~60 seconds (gaming PC ≠ office laptop)
- Requires 2 consecutive bad seconds before firing — single blips are ignored
- Keeps a rolling 5-second pre-lag buffer so it looks *backward* when lag fires

### Cause Diagnosis
Every confirmed lag event gets a plain-English explanation:

| Cause | Example output |
|---|---|
| CPU Spike | *"chrome.exe (PID 4821) was consuming 78% CPU, causing the system to become unresponsive."* |
| RAM Exhaustion | *"System RAM is critically full (14.2 GB / 16 GB). The OS is writing memory to disk (paging)."* |
| Background Cluster | *"6 background processes are each consuming CPU, totalling ~52% combined."* |
| Disk I/O | *"CPU was normal (18%) but responsiveness was 210ms. Likely a disk bottleneck — antivirus, updates, or backup."* |
| Scheduler Contention | *"System under general stress — no single clear cause identified."* |

### Event History
- Every lag event saved to a local SQLite database — history survives restarts
- Click any past event to see: cause card, peak metrics, pre-lag sparkline timeline, top processes table

---

## 🏗 Building the .exe Yourself (Windows)

If you want to build `LagLens.exe` from source:

```bat
git clone https://github.com/YOUR_USERNAME/laglens.git
cd laglens
build_windows.bat
```

The script installs all dependencies and runs PyInstaller automatically.
Output: `dist\LagLens.exe` — a single portable file.

---

## 🏛 Architecture

```
main.py                 Entry point — wires all components
core/
  models.py             Data structures (SystemSample, LagEvent, LagSnapshot)
  collectors.py         Background thread: CPU, RAM, processes, responsiveness probe
  detection.py          Sigmoid scoring, rolling window, baseline learning, state machine
  analyzer.py           5-rule cause engine → plain-English explanations
  recorder.py           5-second pre-lag rolling buffer + snapshot capture
  storage.py            SQLite persistence via SQLAlchemy
ui/
  main_window.py        Live metrics bar, status dot, tray icon, signal wiring
  event_log.py          Scrollable event list with severity colour + cause badges
  detail_panel.py       Cause card, peak chips, sparkline timeline, process table
```

---

## 🧪 Tests

```bash
python tests/test_detection.py
# 16 tests — detection engine, cause analyzer, sigmoid math, false-positive prevention
```

---

## 🗺 Roadmap

- [ ] Disk I/O collector (`psutil.disk_io_counters`)
- [ ] Network spike detection  
- [ ] Export history to CSV
- [ ] ML-based classifier (Decision Tree trained on your collected events)
- [ ] Settings panel (custom thresholds, interval)

---

## 📄 License

MIT — see [LICENSE](LICENSE)
