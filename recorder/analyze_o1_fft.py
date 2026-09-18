#!/usr/bin/env python3
"""
Single-channel O1 EEG FFT analyzer.

This script:

Loads one EEG recording from EEG_Dataset/
Uses channel 0 as O1
Estimates the sampling rate from timestamps
Converts ADC values to volts
Removes the 50 Hz power-line component
Applies a 0.5-45 Hz bandpass filter
Computes and plots a single FFT

Example:
    python analyze_o1_fft.py --state Eyes_Closed --subject Lakshya

Optional:
    python analyze_o1_fft.py --state Eyes_Closed --subject Lakshya --date 2026-07-13
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt, iirnotch

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

DEFAULT_DATASET_ROOT = Path("EEG_Dataset")

# Channel 0 = O1
O1_CHANNEL = 0

NOTCH_FREQ_HZ = 50.0
NOTCH_Q = 30.0

BANDPASS_LOW_HZ = 0.5
BANDPASS_HIGH_HZ = 45.0

ADC_MAX_COUNTS = 4095.0
ADC_REF_VOLTAGE = 3.3


# ---------------------------------------------------------------------
# Dataset discovery
# ---------------------------------------------------------------------

def normalize_name(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def discover_session(
    root: Path,
    subject: Optional[str],
    state: str,
    date: Optional[str],
) -> Tuple[Path, Path, Path]:

    state_key = normalize_name(state)
    subject_key = normalize_name(subject) if subject else None

    candidates = []

    for csv_path in root.rglob("recording.csv"):
        session_folder = csv_path.parent
        metadata_path = session_folder / "metadata.json"

        if not metadata_path.exists():
            continue

        folder_parts = {
            normalize_name(part)
            for part in session_folder.parts
        }

        if normalize_name(session_folder.name) != state_key:
            continue

        if subject_key and subject_key not in folder_parts:
            continue

        if date and date not in folder_parts:
            continue

        candidates.append(
            (session_folder, csv_path, metadata_path)
        )

    if not candidates:
        raise FileNotFoundError(
            f"No session found for "
            f"state={state!r}, subject={subject!r}, date={date!r} "
            f"under {root}"
        )

    if len(candidates) > 1:
        names = "\n".join(
            f"  - {item[0]}"
            for item in candidates
        )

        raise ValueError(
            "Multiple matching sessions found. "
            "Use --subject and/or --date:\n"
            f"{names}"
        )

    return candidates[0]


# ---------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------

def load_session(
    csv_path: Path,
    metadata_path: Path,
) -> Tuple[pd.DataFrame, Dict[str, object]]:

    df = pd.read_csv(csv_path)

    with open(metadata_path, "r", encoding="utf-8") as handle:
        metadata = json.load(handle)

    return df, metadata


# ---------------------------------------------------------------------
# Sampling rate
# ---------------------------------------------------------------------

def estimate_sampling_rate(
    channel_df: pd.DataFrame,
) -> float:

    channel_df = channel_df.sort_values("timestamp_ms")

    if len(channel_df) < 2:
        raise ValueError(
            "Not enough samples to estimate sampling rate."
        )

    timestamps = channel_df[
        "timestamp_ms"
    ].to_numpy(dtype=np.float64)

    duration_s = (
        timestamps[-1] - timestamps[0]
    ) / 1000.0

    if duration_s <= 0:
        raise ValueError(
            "Invalid timestamps; cannot estimate sampling rate."
        )

    fs = (len(timestamps) - 1) / duration_s

    return float(fs)


# ---------------------------------------------------------------------
# ADC conversion
# ---------------------------------------------------------------------

def adc_to_volts(
    signal: np.ndarray,
) -> np.ndarray:

    return (
        signal.astype(np.float64)
        * (ADC_REF_VOLTAGE / ADC_MAX_COUNTS)
    )


# ---------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------

def filter_signal(
    signal: np.ndarray,
    fs: float,
) -> np.ndarray:

    # Convert ADC counts to volts
    volts = adc_to_volts(signal)

    # Remove DC offset
    centered = volts - np.mean(volts)

    # -------------------------------------------------------------
    # 50 Hz notch filter
    # -------------------------------------------------------------

    b_notch, a_notch = iirnotch(
        NOTCH_FREQ_HZ,
        NOTCH_Q,
        fs,
    )

    notched = filtfilt(
        b_notch,
        a_notch,
        centered,
    )

    # -------------------------------------------------------------
    # 0.5-45 Hz bandpass filter
    # -------------------------------------------------------------

    nyquist = fs / 2.0

    high = min(
        BANDPASS_HIGH_HZ,
        nyquist * 0.95,
    )

    if BANDPASS_LOW_HZ >= high:
        raise ValueError(
            f"Sampling rate ({fs:.2f} Hz) is too low "
            f"for a 0.5-45 Hz bandpass."
        )

    b_band, a_band = butter(
        4,
        [BANDPASS_LOW_HZ, high],
        btype="bandpass",
        fs=fs,
    )

    filtered = filtfilt(
        b_band,
        a_band,
        notched,
    )

    return filtered


# ---------------------------------------------------------------------
# FFT
# ---------------------------------------------------------------------

def compute_fft(
    signal: np.ndarray,
    fs: float,
) -> Tuple[np.ndarray, np.ndarray]:

    n = len(signal)

    # Real FFT
    fft_values = np.fft.rfft(signal)

    # Frequency axis
    frequencies = np.fft.rfftfreq(
        n,
        d=1.0 / fs,
    )

    # Amplitude spectrum
    magnitude = np.abs(fft_values) / n

    # Convert to single-sided amplitude spectrum
    if n > 1:
        magnitude[1:-1] *= 2.0

    return frequencies, magnitude


# ---------------------------------------------------------------------
# Plot FFT
# ---------------------------------------------------------------------

def plot_fft(
    frequencies: np.ndarray,
    magnitude: np.ndarray,
    fs: float,
    duration_s: float,
    output_path: Path,
) -> None:

    # Display only 0-45 Hz
    mask = frequencies <= 45.0

    fig, ax = plt.subplots(
        figsize=(12, 6)
    )

    ax.plot(
        frequencies[mask],
        magnitude[mask],
        color="#1f2937",
        linewidth=1.2,
    )

    # -------------------------------------------------------------
    # EEG frequency bands
    # -------------------------------------------------------------

    ax.axvspan(
        0.5,
        4,
        color="#ef4444",
        alpha=0.10,
        label="Delta (0.5-4 Hz)",
    )

    ax.axvspan(
        4,
        8,
        color="#f97316",
        alpha=0.10,
        label="Theta (4-8 Hz)",
    )

    ax.axvspan(
        8,
        13,
        color="#22c55e",
        alpha=0.10,
        label="Alpha (8-13 Hz)",
    )

    ax.axvspan(
        13,
        30,
        color="#3b82f6",
        alpha=0.10,
        label="Beta (13-30 Hz)",
    )

    ax.axvspan(
        30,
        45,
        color="#8b5cf6",
        alpha=0.10,
        label="Gamma (30-45 Hz)",
    )

    # -------------------------------------------------------------
    # Axis labels
    # -------------------------------------------------------------

    ax.set_xlim(
        0,
        min(45.0, fs / 2.0),
    )

    ax.set_xlabel(
        "Frequency (Hz)",
        fontsize=11,
    )

    ax.set_ylabel(
        "Amplitude (V)",
        fontsize=11,
    )

    ax.set_title(
        f"O1 EEG FFT — Channel {O1_CHANNEL}\n"
        f"Sampling rate = {fs:.2f} Hz | "
        f"Duration = {duration_s:.2f} s",
        fontsize=14,
    )

    ax.grid(
        True,
        alpha=0.25,
    )

    ax.legend(
        loc="upper right"
    )

    fig.tight_layout()

    # -------------------------------------------------------------
    # Save figure
    # -------------------------------------------------------------

    fig.savefig(
        output_path,
        dpi=180,
        bbox_inches="tight",
    )

    print(
        f"Saved FFT plot to: {output_path}"
    )

    # Show interactively if possible
    if "agg" not in plt.get_backend().lower():
        plt.show()


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main() -> None:

    parser = argparse.ArgumentParser(
        description="Compute FFT for O1 EEG channel."
    )

    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=DEFAULT_DATASET_ROOT,
        help="EEG dataset root folder",
    )

    parser.add_argument(
        "--subject",
        type=str,
        default=None,
        help="Subject folder name, e.g. Lakshya",
    )

    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Session date, e.g. 2026-07-13",
    )

    parser.add_argument(
        "--state",
        type=str,
        required=True,
        help="State folder, e.g. Eyes_Closed",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PNG path",
    )

    args = parser.parse_args()

    # -------------------------------------------------------------
    # Find session
    # -------------------------------------------------------------

    session_folder, csv_path, metadata_path = discover_session(
        args.dataset_root,
        args.subject,
        args.state,
        args.date,
    )

    # -------------------------------------------------------------
    # Load data
    # -------------------------------------------------------------

    df, metadata = load_session(
        csv_path,
        metadata_path,
    )

    required_columns = {
        "timestamp_ms",
        "channel",
        "adc",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"CSV is missing required columns: "
            f"{sorted(missing)}"
        )

    # -------------------------------------------------------------
    # Select O1 only
    # -------------------------------------------------------------

    o1_df = df[
        df["channel"] == O1_CHANNEL
    ].copy()

    if len(o1_df) < 16:
        raise ValueError(
            f"Channel {O1_CHANNEL} (O1) does not contain "
            f"enough samples for FFT analysis."
        )

    o1_df = o1_df.sort_values(
        "timestamp_ms"
    )

    # -------------------------------------------------------------
    # Estimate sampling rate
    # -------------------------------------------------------------

    fs = estimate_sampling_rate(
        o1_df
    )

    # -------------------------------------------------------------
    # Extract raw ADC data
    # -------------------------------------------------------------

    raw_adc = o1_df[
        "adc"
    ].to_numpy(
        dtype=np.float64
    )

    duration_s = (
        len(raw_adc) - 1
    ) / fs

    # -------------------------------------------------------------
    # Filter O1
    # -------------------------------------------------------------

    filtered_o1 = filter_signal(
        raw_adc,
        fs,
    )

    # -------------------------------------------------------------
    # Compute FFT
    # -------------------------------------------------------------

    frequencies, magnitude = compute_fft(
        filtered_o1,
        fs,
    )

    # -------------------------------------------------------------
    # Find dominant frequency
    # -------------------------------------------------------------

    positive = frequencies > 0

    if np.any(positive):

        positive_frequencies = frequencies[
            positive
        ]

        positive_magnitude = magnitude[
            positive
        ]

        peak_index = np.argmax(
            positive_magnitude
        )

        peak_frequency = float(
            positive_frequencies[peak_index]
        )

        peak_amplitude = float(
            positive_magnitude[peak_index]
        )

    else:
        peak_frequency = 0.0
        peak_amplitude = 0.0

    # -------------------------------------------------------------
    # Console output
    # -------------------------------------------------------------

    print()
    print("=" * 60)
    print("O1 EEG FFT ANALYSIS")
    print("=" * 60)

    print(
        f"Session:                 {session_folder}"
    )

    print(
        f"Channel:                 {O1_CHANNEL} (O1)"
    )

    print(
        f"Metadata sampling rate:  "
        f"{metadata.get('sampling_rate', 'unknown')} Hz"
    )

    print(
        f"Estimated sampling rate: "
        f"{fs:.2f} Hz"
    )

    print(
        f"Samples:                 {len(raw_adc)}"
    )

    print(
        f"Duration:                {duration_s:.2f} s"
    )

    print(
        f"Dominant frequency:      "
        f"{peak_frequency:.2f} Hz"
    )

    print(
        f"Peak amplitude:          "
        f"{peak_amplitude:.6f} V"
    )

    print("=" * 60)

    # -------------------------------------------------------------
    # Output path
    # -------------------------------------------------------------

    if args.output is None:

        output_dir = (
            session_folder / "analysis"
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            output_dir
            / f"{session_folder.name}_O1_FFT.png"
        )

    else:
        output_path = args.output

    # -------------------------------------------------------------
    # Plot
    # -------------------------------------------------------------

    plot_fft(
        frequencies,
        magnitude,
        fs,
        duration_s,
        output_path,
    )


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

if __name__ == "__main__":
    main()
