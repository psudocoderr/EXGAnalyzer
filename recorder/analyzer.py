#!/usr/bin/env python3
"""
analyzer.py

Replays a CSV recorded by recorder.py and runs the filtering + FFT
analysis on it post hoc -- no hardware or live connection needed.

Usage:
    python analyzer.py --csv eeg_session_20260908_143012.csv
    python analyzer.py --csv session.csv --output session_plot.png
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import butter, filtfilt, spectrogram

# --- DSP configuration (matches Live_EEG_viewer.py's filter design) ---
BANDSTOP_LOW_HZ = 48.0
BANDSTOP_HIGH_HZ = 52.0
BANDPASS_LOW_HZ = 2.0
BANDPASS_HIGH_HZ = 45.0
ADC_MAX_COUNTS = 4095.0
ADC_REF_VOLTAGE = 3.3


def load_csv(csv_path: Path) -> tuple[np.ndarray, np.ndarray]:
    elapsed_s: list[float] = []
    raw_value: list[float] = []
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if len(row) < 2:
                continue
            elapsed_s.append(float(row[0]))
            raw_value.append(float(row[1]))

    if len(raw_value) < 32:
        print(f"[Error] Only {len(raw_value)} samples in {csv_path} -- need at least 32 to filter.")
        sys.exit(1)

    return np.array(elapsed_s, dtype=np.float64), np.array(raw_value, dtype=np.float64)


def estimate_fs(elapsed_s: np.ndarray) -> float:
    duration = elapsed_s[-1] - elapsed_s[0]
    return (len(elapsed_s) - 1) / duration


def filter_signal(raw: np.ndarray, fs: float) -> np.ndarray:
    volts = (raw / ADC_MAX_COUNTS) * ADC_REF_VOLTAGE
    centered = volts - np.mean(volts)

    b_notch, a_notch = butter(4, [BANDSTOP_LOW_HZ, BANDSTOP_HIGH_HZ], btype="bandstop", fs=fs)
    notched = filtfilt(b_notch, a_notch, centered)

    b_bp, a_bp = butter(6, [BANDPASS_LOW_HZ, BANDPASS_HIGH_HZ], btype="bandpass", fs=fs)
    return filtfilt(b_bp, a_bp, notched)


def analyze(csv_path: Path, output_path: Path) -> None:
    elapsed_s, raw = load_csv(csv_path)
    fs = estimate_fs(elapsed_s)
    print(f"Loaded {len(raw)} samples from {csv_path}, estimated fs = {fs:.2f} Hz")

    filtered = filter_signal(raw, fs)

    n = len(filtered)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    fft_mag = np.abs(np.fft.rfft(filtered)) / n

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 10))
    fig.canvas.manager.set_window_title("EEG Post-Collection Analysis")

    ax1.plot(elapsed_s, filtered, color="#1f2937", linewidth=0.8)
    ax1.set_title("Filtered Time Domain (DC Centered)")
    ax1.set_xlabel("Time (Seconds)")
    ax1.set_ylabel("Volts (V)")
    ax1.grid(True, alpha=0.3)

    mask = freqs <= 60.0
    ax2.plot(freqs[mask], fft_mag[mask], color="#3b82f6", linewidth=1.2)
    ax2.set_title(f"Filtered FFT ({BANDPASS_LOW_HZ:.1f}-{BANDPASS_HIGH_HZ:.0f} Hz Bandpass + "
                  f"{BANDSTOP_LOW_HZ:.0f}-{BANDSTOP_HIGH_HZ:.0f} Hz Bandstop)")
    ax2.set_xlabel("Frequency (Hz)")
    ax2.set_ylabel("Magnitude (V)")
    ax2.grid(True, alpha=0.3)

    bands = [
        (0.5, 4, "red", "Delta"),
        (4, 8, "orange", "Theta"),
        (8, 13, "green", "Alpha"),
        (13, 30, "blue", "Beta"),
        (30, 45, "purple", "Gamma"),
    ]
    for lo, hi, color, label in bands:
        ax2.axvspan(lo, hi, color=color, alpha=0.08, label=label)
    ax2.legend(loc="upper right")

    nperseg = min(n, max(32, int(fs * 2)))
    noverlap = nperseg // 2
    spec_freqs, spec_times, spec_power = spectrogram(filtered, fs=fs, nperseg=nperseg, noverlap=noverlap)
    spec_mask = spec_freqs <= 60.0
    spec_db = 10 * np.log10(spec_power[spec_mask] + 1e-12)

    mesh = ax3.pcolormesh(spec_times, spec_freqs[spec_mask], spec_db, shading="gouraud", cmap="viridis")
    ax3.set_title("Filtered Spectrogram")
    ax3.set_xlabel("Time (Seconds)")
    ax3.set_ylabel("Frequency (Hz)")
    fig.colorbar(mesh, ax=ax3, label="Power (dB)")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    print(f"Saved plot to {output_path.resolve()}")
    plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a recorder.py CSV and analyze it")
    parser.add_argument("--csv", type=Path, required=True, help="CSV file written by recorder.py")
    parser.add_argument("--output", type=Path, default=None,
                         help="Path to save the analysis plot PNG (default: <csv name>.png)")
    args = parser.parse_args()

    output_path = args.output or args.csv.with_suffix(".png")
    analyze(args.csv, output_path)


if __name__ == "__main__":
    main()
