#!/usr/bin/env python3
"""
EEG DATA RECORDER v3
--------------------
Simple CLI recorder that reads CSV data from an ESP32 over USB Serial
and saves it to a timestamped CSV file with metadata.

Designed for BioSignal-Recorder-v3 firmware (serial-only, no WiFi).

Usage:
    python eegrecorder-v3.py                     # auto-detect serial port
    python eegrecorder-v3.py --port /dev/ttyUSB0 # specify port
    python eegrecorder-v3.py --port COM3 --duration 300
"""

import sys
import os
import time
import json
import csv
import signal
import argparse
from datetime import datetime
from pathlib import Path

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("[Error] pyserial is required. Install it with:")
    print("        pip install pyserial")
    sys.exit(1)


# ── Configuration ─────────────────────────────────────────────
BAUD_RATE = 115200
CSV_HEADER = ["timestamp_ms", "channel", "gpio", "adc", "packet"]

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


# ── Helpers ───────────────────────────────────────────────────
def get_input(prompt: str, default: str) -> str:
    user_in = input(f"  {prompt} [{default}]: ").strip()
    return user_in if user_in else default


def find_serial_port() -> str:
    """Auto-detect the most likely ESP32 serial port."""
    ports = serial.tools.list_ports.comports()
    esp_ports = []
    for p in ports:
        desc = (p.description or "").lower()
        hwid = (p.hwid or "").lower()
        # Common ESP32 USB-UART chips
        if any(kw in desc for kw in ["cp210", "ch340", "ch910", "ftdi", "usb-serial", "uart"]):
            esp_ports.append(p)
        elif any(kw in hwid for kw in ["10c4:ea60", "1a86:7523", "1a86:55d4", "0403:6001"]):
            esp_ports.append(p)

    if not esp_ports:
        # Fall back to showing all available ports
        if ports:
            print("\n  Available serial ports:")
            for i, p in enumerate(ports, 1):
                print(f"    {i}) {p.device}  — {p.description}")
            while True:
                sel = input(f"  Select port [1-{len(ports)}]: ").strip()
                try:
                    idx = int(sel) - 1
                    if 0 <= idx < len(ports):
                        return ports[idx].device
                except ValueError:
                    pass
                print("  Invalid selection.")
        else:
            print("[Error] No serial ports found. Is the ESP32 plugged in?")
            sys.exit(1)

    if len(esp_ports) == 1:
        print(f"  Auto-detected: {esp_ports[0].device} ({esp_ports[0].description})")
        return esp_ports[0].device

    print("\n  Multiple ESP32 candidates found:")
    for i, p in enumerate(esp_ports, 1):
        print(f"    {i}) {p.device}  — {p.description}")
    while True:
        sel = input(f"  Select port [1-{len(esp_ports)}]: ").strip()
        try:
            idx = int(sel) - 1
            if 0 <= idx < len(esp_ports):
                return esp_ports[idx].device
        except ValueError:
            pass
        print("  Invalid selection.")


def create_output_dir(meta: dict) -> Path:
    """Create organized output directory: EEG_Dataset/Subject/Date/Task/"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    base = (
        Path("EEG_Dataset")
        / meta["subject"].replace(" ", "_")
        / date_str
        / meta["task"].replace(" ", "_")
    )
    folder = base
    counter = 1
    while folder.exists():
        folder = base.with_name(f"{base.name}_{counter:02d}")
        counter += 1
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ── Session Setup ─────────────────────────────────────────────
def setup_session(args) -> dict:
    print("=" * 52)
    print("          EEG DATA RECORDER  v3  (Serial)")
    print("=" * 52)

    meta = {}
    meta["board"] = "ESP32"
    meta["firmware"] = "BioSignal-Recorder-v3"
    meta["sampling_rate"] = 250

    # Serial port
    if args.port:
        meta["port"] = args.port
        print(f"  Port: {args.port}")
    else:
        print("\n  Detecting serial port...")
        meta["port"] = find_serial_port()

    meta["subject"] = get_input("Subject name", "Unknown")

    # Task selection
    print("\n  Tasks:")
    for k, v in TASKS.items():
        print(f"    {k:>2}) {v}")
    task_idx = get_input("Task number", "1")
    if task_idx == "11":
        meta["task"] = get_input("Custom task name", "Custom Task")
    else:
        meta["task"] = TASKS.get(task_idx, "Unknown Task")

    # Duration
    if args.duration:
        meta["duration_seconds"] = args.duration
    else:
        try:
            meta["duration_seconds"] = int(get_input("Duration (seconds)", "120"))
        except ValueError:
            meta["duration_seconds"] = 120

    # Electrode placement
    print()
    meta["channel0_electrode"] = get_input("CH0 electrode position", "O1")
    meta["reference"] = get_input("Reference electrode", "A1")
    meta["session_notes"] = input("  Session notes (optional): ").strip()

    # Summary
    print()
    print("  ─────────────────────────────────────")
    print(f"  Subject       {meta['subject']}")
    print(f"  Task          {meta['task']}")
    print(f"  Duration      {meta['duration_seconds']}s")
    print(f"  Port          {meta['port']}")
    print(f"  Sample Rate   {meta['sampling_rate']} Hz")
    print(f"  CH0 Electrode {meta['channel0_electrode']}")
    print(f"  Reference     {meta['reference']}")
    if meta["session_notes"]:
        print(f"  Notes         {meta['session_notes']}")
    print("  ─────────────────────────────────────")

    input("\n  Press ENTER to begin recording...")
    return meta


# ── Main Recording Loop ──────────────────────────────────────
def record(meta: dict):
    port = meta["port"]
    duration = meta["duration_seconds"]

    # Countdown
    for i in range(3, 0, -1):
        print(f"  Starting in {i}...", end="\r")
        time.sleep(1)
    print("  Recording started!       ")

    # Open serial
    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=1)
    except serial.SerialException as e:
        print(f"\n[Error] Could not open {port}: {e}")
        sys.exit(1)

    # Reset ESP32 by toggling DTR
    ser.setDTR(False)
    time.sleep(0.1)
    ser.setDTR(True)
    ser.reset_input_buffer()

    # Wait for the READY marker from the firmware
    print("  Waiting for ESP32 to boot...", end="", flush=True)
    ready_timeout = time.time() + 10
    header_found = False
    while time.time() < ready_timeout:
        try:
            line = ser.readline().decode("utf-8", errors="replace").strip()
        except Exception:
            continue
        if line == "READY":
            header_found = True
            break
    if not header_found:
        print("\n[Warning] Did not receive READY marker. Proceeding anyway...")
    else:
        print(" OK")

    # Create output directory and files
    folder = create_output_dir(meta)
    csv_path = folder / "recording.csv"
    meta_path = folder / "metadata.json"
    log_path = folder / "recording_log.txt"

    csv_file = open(csv_path, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(CSV_HEADER)

    # Recording state
    sample_count = 0
    bad_lines = 0
    dropped_samples = 0
    gap_events = 0
    last_packet_by_channel = {}
    start_time = time.time()
    stop_requested = False

    def handle_sigint(sig, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, handle_sigint)

    meta["date"] = datetime.now().strftime("%Y-%m-%d")
    meta["start_time"] = datetime.now().strftime("%H:%M:%S")

    print(f"  Saving to: {folder.resolve()}\n")

    try:
        while not stop_requested:
            elapsed = time.time() - start_time
            remaining = max(0, duration - elapsed)

            if elapsed >= duration:
                print("\n\n  ✓ Duration reached.")
                break

            # Read a line from serial
            try:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
            except serial.SerialException:
                print("\n[Error] Serial connection lost.")
                break
            except Exception:
                continue

            if not line:
                continue

            # Skip header/marker lines
            if line.startswith("timestamp_ms") or line == "READY":
                continue

            # Parse CSV: timestamp_ms,channel,gpio,adc,packet
            parts = line.split(",")
            if len(parts) != 5:
                bad_lines += 1
                continue

            try:
                row = [int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])]
            except ValueError:
                bad_lines += 1
                continue

            # Packet continuity check: firmware's `packet` field increments once
            # per emitted sample on a given channel. A gap here means the host
            # missed line(s) on this channel (serial overrun, USB hiccup, etc.) —
            # not just a malformed row, which `bad_lines` already covers.
            channel, packet = row[1], row[4]
            prev_packet = last_packet_by_channel.get(channel)
            if prev_packet is not None:
                gap = packet - prev_packet - 1
                if gap > 0:
                    dropped_samples += gap
                    gap_events += 1
            last_packet_by_channel[channel] = packet

            csv_writer.writerow(row)
            sample_count += 1

            # Live status line (update every 50 samples to avoid slowdown)
            if sample_count % 50 == 0:
                rate = sample_count / elapsed if elapsed > 0 else 0
                status = (
                    f"  Samples: {sample_count:>7,} | "
                    f"Rate: {rate:>6.1f} Hz | "
                    f"Elapsed: {elapsed:>6.1f}s | "
                    f"Remaining: {remaining:>6.1f}s | "
                    f"Bad: {bad_lines} | "
                    f"Dropped: {dropped_samples}"
                )
                print(f"\r{status}", end="", flush=True)

    finally:
        csv_file.close()
        ser.close()

        actual_duration = time.time() - start_time
        avg_rate = sample_count / actual_duration if actual_duration > 0 else 0

        # Save metadata
        meta_save = {k: v for k, v in meta.items() if k != "port"}
        meta_save["end_time"] = datetime.now().strftime("%H:%M:%S")
        meta_save["actual_duration_s"] = round(actual_duration, 1)
        meta_save["total_samples"] = sample_count
        meta_save["effective_rate_hz"] = round(avg_rate, 2)
        meta_save["bad_lines"] = bad_lines
        meta_save["dropped_samples"] = dropped_samples
        meta_save["gap_events"] = gap_events
        meta_save["drop_rate_pct"] = round(
            100.0 * dropped_samples / (sample_count + dropped_samples), 4
        ) if (sample_count + dropped_samples) > 0 else 0.0
        with open(meta_path, "w") as f:
            json.dump(meta_save, f, indent=4)

        # Save recording log
        log_lines = [
            f"Recording Started:    {meta.get('start_time', '?')}",
            f"Recording Ended:      {meta_save['end_time']}",
            f"Actual Duration:      {actual_duration:.1f} s",
            f"Total Samples:        {sample_count}",
            f"Effective Rate:       {avg_rate:.2f} Hz",
            f"Bad/Skipped Lines:    {bad_lines}",
            f"Dropped Samples:      {dropped_samples} ({meta_save['drop_rate_pct']}%, {gap_events} gap event(s))",
            f"CSV File:             {csv_path.name}",
        ]
        with open(log_path, "w") as f:
            f.write("\n".join(log_lines) + "\n")

        print(f"\n\n  ══════════════════════════════════")
        print(f"  Recording complete!")
        print(f"  Samples:   {sample_count:,}")
        print(f"  Duration:  {actual_duration:.1f}s")
        print(f"  Rate:      {avg_rate:.1f} Hz")
        print(f"  Bad lines: {bad_lines}")
        print(f"  Dropped:   {dropped_samples} ({meta_save['drop_rate_pct']}%, {gap_events} gap event(s))")
        print(f"  Saved to:  {folder.resolve()}")
        print(f"  ══════════════════════════════════\n")


# ── Entry point ───────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="EEG Data Recorder v3 (Serial)")
    parser.add_argument("--port", "-p", type=str, default=None,
                        help="Serial port (e.g. /dev/ttyUSB0 or COM3)")
    parser.add_argument("--duration", "-d", type=int, default=None,
                        help="Recording duration in seconds")
    args = parser.parse_args()

    meta = setup_session(args)
    record(meta)


if __name__ == "__main__":
    main()
