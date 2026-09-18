#!/usr/bin/env python3
"""
quick_filter_check.py

Bench sanity tool for BioSignal-Recorder-v3's PROTOCOL_TEXT_DEBUG serial
output (human-readable CSV: timestamp_us,seq,channel,gpio,adc). Captures a
few seconds directly off the serial port, applies the same notch (50Hz) +
bandpass (0.5-45Hz) filter used by analyze_eeg_dataset.py, and plots raw
vs. filtered vs. FFT so you can see whether real EEG rhythms are present
underneath mains hum -- before committing to a full recording session or
building AP/bridge tooling around a signal that might just be noise.

Only works with the firmware's PROTOCOL_TEXT_DEBUG build. Not for the
binary protocol (use recorder/bridge for that).

Usage:
    python quick_filter_check.py --port /dev/ttyUSB0 --duration 15
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import serial
from scipy.signal import butter, filtfilt, iirnotch

from bridge.calibration import NOMINAL_GAIN, CALIBRATION_METHOD

NOTCH_FREQ_HZ = 50.0
NOTCH_Q = 30.0
BANDPASS_LOW_HZ = 0.5
BANDPASS_HIGH_HZ = 45.0
ADC_MAX_COUNTS = 4095.0
ADC_REF_VOLTAGE = 3.3

# filtfilt has an edge transient at the very start/end of the buffer (padded
# reflection meeting the abrupt start of a real recording) that is a filter
# artifact, not signal. Drop it from anything we plot or measure a peak on.
TRIM_SECONDS = 1.0


def read_debug_stream(port: str, baud: int, duration_s: float) -> tuple[np.ndarray, np.ndarray]:
    ser = serial.Serial(port, baud, timeout=1.0)
    ser.reset_input_buffer()

    timestamps_us: list[int] = []
    adc_values: list[int] = []

    deadline = time.time() + duration_s
    print(f"Reading from {port} @ {baud} baud for {duration_s:.0f}s...")
    while time.time() < deadline:
        raw_line = ser.readline().decode("ascii", errors="ignore").strip()
        if not raw_line:
            continue
        if raw_line in ("READY",) or raw_line.startswith("timestamp_us") or raw_line.startswith("[ADC]"):
            print(f"  {raw_line}")
            continue

        parts = raw_line.split(",")
        if len(parts) != 5:
            continue
        try:
            ts_us, _seq, channel, _gpio, adc = (int(p) for p in parts)
        except ValueError:
            continue
        if channel != 0:
            continue
        timestamps_us.append(ts_us)
        adc_values.append(adc)

    ser.close()
    return np.array(timestamps_us, dtype=np.float64), np.array(adc_values, dtype=np.float64)


def estimate_fs(timestamps_us: np.ndarray) -> float:
    duration_s = (timestamps_us[-1] - timestamps_us[0]) / 1e6
    return (len(timestamps_us) - 1) / duration_s


def filter_signal(adc: np.ndarray, fs: float) -> np.ndarray:
    """Returns filtered signal in calibrated microvolts (datasheet-nominal gain)."""
    volts = adc * (ADC_REF_VOLTAGE / ADC_MAX_COUNTS)
    centered = volts - np.mean(volts)

    b_notch, a_notch = iirnotch(NOTCH_FREQ_HZ, NOTCH_Q, fs)
    notched = filtfilt(b_notch, a_notch, centered)

    nyquist = fs / 2.0
    high = min(BANDPASS_HIGH_HZ, nyquist * 0.95)
    b_band, a_band = butter(4, [BANDPASS_LOW_HZ, high], btype="bandpass", fs=fs)
    filtered_volts = filtfilt(b_band, a_band, notched)

    return filtered_volts * 1e6 / NOMINAL_GAIN


def plot(t: np.ndarray, raw: np.ndarray, filtered_uV: np.ndarray, fs: float, output_path: Path) -> None:
    trim_n = int(TRIM_SECONDS * fs)
    if len(filtered_uV) > 2 * trim_n:
        t = t[trim_n:-trim_n]
        raw = raw[trim_n:-trim_n]
        filtered_uV = filtered_uV[trim_n:-trim_n]

    n = len(filtered_uV)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    magnitude = np.abs(np.fft.rfft(filtered_uV)) / n
    if n > 1:
        magnitude[1:-1] *= 2.0

    positive = freqs > 0
    if np.any(positive):
        peak_idx = np.argmax(magnitude[positive])
        peak_freq = freqs[positive][peak_idx]
        peak_amp = magnitude[positive][peak_idx]
        print(f"Dominant frequency (after trimming {TRIM_SECONDS}s edge transient): "
              f"{peak_freq:.2f} Hz @ {peak_amp:.1f} uV")

    fig, axes = plt.subplots(3, 1, figsize=(12, 10))

    axes[0].plot(t, raw, color="#94a3b8", linewidth=0.8)
    axes[0].set_title("Raw ADC counts (unfiltered)")
    axes[0].set_ylabel("ADC counts")
    axes[0].grid(alpha=0.25)

    axes[1].plot(t, filtered_uV, color="#1f2937", linewidth=0.8)
    axes[1].set_title(f"Notch(50Hz) + Bandpass(0.5-45Hz) filtered  [{CALIBRATION_METHOD}, gain={NOMINAL_GAIN}]")
    axes[1].set_ylabel("uV")
    axes[1].set_xlabel("Time (s)")
    axes[1].grid(alpha=0.25)

    mask = freqs <= 45.0
    axes[2].plot(freqs[mask], magnitude[mask], color="#1f2937", linewidth=1.2)
    bands = [
        (0.5, 4, "#ef4444", "Delta"),
        (4, 8, "#f97316", "Theta"),
        (8, 13, "#22c55e", "Alpha"),
        (13, 30, "#3b82f6", "Beta"),
        (30, 45, "#8b5cf6", "Gamma"),
    ]
    for lo, hi, color, label in bands:
        axes[2].axvspan(lo, hi, color=color, alpha=0.10, label=label)
    axes[2].set_title("FFT of filtered signal")
    axes[2].set_xlabel("Frequency (Hz)")
    axes[2].set_ylabel("Amplitude (uV)")
    axes[2].set_xlim(0, min(45.0, fs / 2.0))
    axes[2].legend(loc="upper right", fontsize=8)
    axes[2].grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    print(f"Saved plot to {output_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick raw-vs-filtered sanity check for v3 serial debug output")
    parser.add_argument("--port", required=True, help="Serial port, e.g. /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--duration", type=float, default=15.0, help="Seconds to capture")
    parser.add_argument("--output", type=Path, default=Path("quick_filter_check.png"))
    args = parser.parse_args()

    ts_us, adc = read_debug_stream(args.port, args.baud, args.duration)
    if len(adc) < 32:
        print(f"[Error] Only captured {len(adc)} samples -- need at least 32 for filtering. "
              f"Is the firmware built with PROTOCOL_TEXT_DEBUG defined?")
        sys.exit(1)

    fs = estimate_fs(ts_us)
    print(f"Captured {len(adc)} samples, estimated fs = {fs:.2f} Hz")

    filtered_uV = filter_signal(adc, fs)
    t = (ts_us - ts_us[0]) / 1e6

    plot(t, adc, filtered_uV, fs, args.output)


if __name__ == "__main__":
    main()
