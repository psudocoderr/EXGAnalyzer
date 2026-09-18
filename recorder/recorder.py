#!/usr/bin/env python3
"""
recorder.py

Dumb capture: connects to the nRF52840's serial stream (one value per
line) and writes every sample straight to a CSV, with no filtering or
plotting. Pair with analyzer.py, which replays the CSV afterward and
does the actual filtering/FFT analysis.

Usage:
    python recorder.py --port /dev/ttyACM0 --duration 30
    python recorder.py --port /dev/ttyACM0 --duration 30 --csv session.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

import serial


def record(port: str, baud: int, duration_s: float, csv_path: Path) -> None:
    ser = serial.Serial(port, baud, timeout=1.0)
    ser.reset_input_buffer()

    print(f"Connected to {port} @ {baud} baud. Recording for {duration_s:.0f}s...")

    rows: list[tuple[float, float]] = []
    start_time: float | None = None
    deadline = time.time() + duration_s

    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        try:
            value = float(line.split(",")[0])
        except ValueError:
            print(f"Ignoring invalid line: {line}")
            continue

        now = time.time()
        if start_time is None:
            start_time = now
        rows.append((now - start_time, value))
        print(line)

    ser.close()

    if not rows:
        print("[Error] No samples recorded.")
        sys.exit(1)

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["elapsed_s", "value"])
        writer.writerows(rows)

    print(f"Recorded {len(rows)} samples to {csv_path.resolve()}")
    print(f"Analyze it with:\n  python analyzer.py --csv {csv_path}")


DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "v7.5"


def main() -> None:
    parser = argparse.ArgumentParser(description="Record the EEG serial stream to a CSV for later analysis")
    parser.add_argument("--port", default="/dev/ttyUSB0", help="Serial port, e.g. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=120.0, help="Seconds to record")
    parser.add_argument("--csv", type=Path, default=None,
                         help="Output CSV path (default: timestamped filename under data/)")
    args = parser.parse_args()

    if args.csv is not None:
        csv_path = args.csv
    else:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        csv_path = DATA_DIR / f"eeg_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    record(args.port, args.baud, args.duration, csv_path)


if __name__ == "__main__":
    main()
