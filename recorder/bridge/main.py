#!/usr/bin/env python3
"""
EEG Data Recorder — bridge CLI

Records from BioSignal-Recorder-v3 firmware (binary framed protocol,
protocol.py) over USB serial, validating frame integrity (CRC16 +
sequence continuity) as it goes, and writes a session under EEG_Dataset/
with the same structure the offline analyzer expects.

This supersedes eegrecorder-v3.py, which spoke the old plain-CSV
protocol that the firmware no longer emits by default (only under a
PROTOCOL_TEXT_DEBUG build, for bench bring-up).

Usage:
    python -m bridge.main
    python -m bridge.main --port /dev/ttyUSB0 --duration 300
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

try:
    import serial.tools.list_ports
except ImportError:
    print("[Error] pyserial is required. Install it with:")
    print("        pip install pyserial")
    sys.exit(1)

from . import protocol
from .serial_reader import SerialFrameReader
from .session import Session, SessionMeta

BAUD_RATE = 921600
DATASET_DIR = Path("EEG_Dataset")

TASKS = {
    "1": "Eyes Open",
    "2": "Eyes Closed",
    "3": "Mental Arithmetic",
    "4": "Reading",
    "5": "Deep Breathing",
    "6": "Meditation",
    "7": "Blink",
    "8": "Jaw Clench",
    "9": "Eye Movement",
    "10": "Speaking",
    "11": "Custom",
}


class JitterTracker:
    """O(1)-memory running mean/variance of inter-tick timestamp deltas
    (Welford's algorithm) — avoids buffering every delta for long sessions."""

    def __init__(self):
        self.last_ts = None
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.min_delta = None
        self.max_delta = None

    def update(self, ts_us: int):
        if self.last_ts is not None:
            delta = ts_us - self.last_ts
            self.n += 1
            d = delta - self.mean
            self.mean += d / self.n
            d2 = delta - self.mean
            self.m2 += d * d2
            self.min_delta = delta if self.min_delta is None else min(self.min_delta, delta)
            self.max_delta = delta if self.max_delta is None else max(self.max_delta, delta)
        self.last_ts = ts_us

    def measured_rate_hz(self) -> float:
        return 1e6 / self.mean if self.mean > 0 else 0.0

    def stats(self) -> dict:
        if self.n < 2:
            return {}
        variance = self.m2 / (self.n - 1)
        return {
            "mean_interval_us": round(self.mean, 2),
            "stddev_us": round(variance ** 0.5, 2),
            "min_interval_us": self.min_delta,
            "max_interval_us": self.max_delta,
            "n_intervals": self.n,
        }


def get_input(prompt: str, default: str) -> str:
    user_in = input(f"  {prompt} [{default}]: ").strip()
    return user_in if user_in else default


def find_serial_port() -> str:
    ports = serial.tools.list_ports.comports()
    esp_ports = []
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        if any(kw in desc for kw in ["cp210", "ch340", "ch910", "ftdi", "usb-serial", "uart"]):
            esp_ports.append(p)
        elif any(kw in hwid for kw in ["10c4:ea60", "1a86:7523", "1a86:55d4", "0403:6001"]):
            esp_ports.append(p)

    candidates = esp_ports or list(ports)
    if not candidates:
        print("[Error] No serial ports found. Is the ESP32 plugged in?")
        sys.exit(1)
    if len(candidates) == 1:
        print(f"  Auto-detected: {candidates[0].device} ({candidates[0].description})")
        return candidates[0].device

    print("\n  Multiple candidates found:")
    for i, p in enumerate(candidates, 1):
        print(f"    {i}) {p.device}  — {p.description}")
    while True:
        sel = input(f"  Select port [1-{len(candidates)}]: ").strip()
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx].device
        except ValueError:
            pass
        print("  Invalid selection.")


def setup_session_inputs(args) -> dict:
    print("=" * 52)
    print("     EEG DATA RECORDER — bridge (binary/serial)")
    print("=" * 52)

    inputs = {}
    inputs["port"] = args.port or find_serial_port()

    inputs["subject"] = get_input("Subject name", "Unknown")

    print("\n  Tasks:")
    for k, v in TASKS.items():
        print(f"    {k:>2}) {v}")
    task_idx = get_input("Task number", "1")
    inputs["task"] = (
        get_input("Custom task name", "Custom Task") if task_idx == "11"
        else TASKS.get(task_idx, "Unknown Task")
    )

    if args.duration:
        inputs["duration_seconds"] = args.duration
    else:
        try:
            inputs["duration_seconds"] = int(get_input("Duration (seconds)", "120"))
        except ValueError:
            inputs["duration_seconds"] = 120

    inputs["reference"] = get_input("Reference electrode", "A1")
    inputs["session_notes"] = input("  Session notes (optional): ").strip()
    return inputs


def record(inputs: dict):
    reader = SerialFrameReader(inputs["port"], baud=BAUD_RATE, timeout=1.0)
    print(f"\n  Connecting to {inputs['port']} @ {BAUD_RATE} baud...")
    reader.open()

    print("  Waiting for CONFIG frame from firmware...", end="", flush=True)
    try:
        config = reader.wait_for_config(timeout_s=10.0)
    except TimeoutError:
        print("\n[Error] No CONFIG frame received. Is BioSignal-Recorder-v3 flashed and running?")
        reader.close()
        sys.exit(1)
    print(" OK")
    print(f"  Channels: {[c.label for c in config.channels]}  "
          f"@ {config.sample_rate_hz} Hz, {config.adc_bits}-bit ADC")
    for ch in config.channels:
        status = "OK" if ch.selftest_ok else "UNTESTED"
        print(f"    CH -> GPIO{ch.gpio:<2} ({ch.label:<4}) self-test: {status}")

    meta = SessionMeta(
        subject=inputs["subject"],
        task=inputs["task"],
        sampling_rate_hz=config.sample_rate_hz,
        adc_bits=config.adc_bits,
        adc_atten_db=config.adc_atten_db,
        channels=[
            {"index": i, "gpio": c.gpio, "label": c.label, "selftest_ok": c.selftest_ok}
            for i, c in enumerate(config.channels)
        ],
        reference_electrode=inputs["reference"],
        session_notes=inputs["session_notes"],
    )
    session = Session(DATASET_DIR, meta)
    session.open()
    print(f"  Saving to: {session.folder.resolve()}\n")

    jitter = JitterTracker()
    stop_requested = False

    def handle_sigint(sig, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, handle_sigint)

    duration = inputs["duration_seconds"]
    start_time = time.time()

    for i in range(3, 0, -1):
        print(f"  Starting in {i}...", end="\r")
        time.sleep(1)
    print("  Recording started!       ")
    start_time = time.time()

    try:
        for sample in reader.stream_samples():
            jitter.update(sample.timestamp_us)
            for ch_idx, adc_value in enumerate(sample.values):
                gpio = config.channels[ch_idx].gpio
                session.write_sample(sample.timestamp_us, sample.seq, ch_idx, gpio, adc_value)

            elapsed = time.time() - start_time
            if session.sample_count % 50 == 0:
                remaining = max(0, duration - elapsed)
                status = (
                    f"  Ticks: {session.sample_count // max(1, len(config.channels)):>7,} | "
                    f"Rate: {jitter.measured_rate_hz():>6.1f} Hz | "
                    f"Elapsed: {elapsed:>6.1f}s | Remaining: {remaining:>6.1f}s | "
                    f"Dropped: {reader.stats.frames_dropped} | Corrupt: {reader.stats.frames_corrupted}"
                )
                print(f"\r{status}", end="", flush=True)

            if stop_requested or elapsed >= duration:
                break
    finally:
        reader.close()
        meta_out = session.close(reader.stats, jitter.measured_rate_hz(), jitter.stats())

        print(f"\n\n  ══════════════════════════════════")
        print(f"  Recording complete!")
        print(f"  Samples:      {meta_out['total_samples']:,}")
        print(f"  Duration:     {meta_out['actual_duration_s']:.1f}s")
        print(f"  Measured Hz:  {meta_out['measured_sampling_rate_hz']}")
        print(f"  Dropped:      {meta_out['frames_dropped']} ({meta_out['drop_rate_pct']}%)")
        print(f"  Corrupted:    {meta_out['frames_corrupted']}")
        print(f"  Calibration:  {meta_out['calibration_method']} (gain={meta_out['calibration_gain']})")
        print(f"  Saved to:     {session.folder.resolve()}")
        print(f"  ══════════════════════════════════\n")


def main():
    parser = argparse.ArgumentParser(description="EEG Data Recorder — bridge (binary/serial)")
    parser.add_argument("--port", "-p", type=str, default=None,
                         help="Serial port (e.g. /dev/ttyUSB0 or COM3)")
    parser.add_argument("--duration", "-d", type=int, default=None,
                         help="Recording duration in seconds")
    args = parser.parse_args()

    inputs = setup_session_inputs(args)
    input("\n  Press ENTER to begin recording...")
    record(inputs)


if __name__ == "__main__":
    main()
