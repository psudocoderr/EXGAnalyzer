"""
session.py

Recording session lifecycle: output directory management, CSV writing,
and metadata.json — the same code path whether triggered from the CLI
(main.py) or the dashboard's REST control (server.py, Phase 3), so both
produce equivalent output.

Keeps the existing EEG_Dataset/Subject/Date/Task/ folder convention from
the earlier recorder scripts for continuity.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import calibration

CSV_HEADER = ["timestamp_us", "seq", "channel", "gpio", "adc", "crc_ok"]


def create_output_dir(base_dir: Path, subject: str, task: str) -> Path:
    """Creates EEG_Dataset/Subject/Date/Task[_NN]/ and returns the path."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    base = base_dir / subject.replace(" ", "_") / date_str / task.replace(" ", "_")
    folder = base
    counter = 1
    while folder.exists():
        folder = base.with_name(f"{base.name}_{counter:02d}")
        counter += 1
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@dataclass
class SessionMeta:
    subject: str
    task: str
    board: str = "ESP32"
    firmware: str = "BioSignal-Recorder-v3"
    protocol_version: int = 1
    sampling_rate_hz: int = 250
    adc_bits: int = 12
    adc_atten_db: int = 11
    channels: list[dict] = field(default_factory=list)
    calibration_method: str = calibration.CALIBRATION_METHOD
    calibration_gain: float = calibration.NOMINAL_GAIN
    reference_electrode: str = "A1"
    session_notes: str = ""


class Session:
    """One recording session: owns the CSV file + metadata.json for one run."""

    def __init__(self, base_dir: Path, meta: SessionMeta):
        self.meta = meta
        self.folder = create_output_dir(base_dir, meta.subject, meta.task)
        self.csv_path = self.folder / "recording.csv"
        self.meta_path = self.folder / "metadata.json"
        self.log_path = self.folder / "recording_log.txt"
        self._csv_file = None
        self._csv_writer = None
        self._start_dt = None
        self.sample_count = 0

    def open(self):
        self._csv_file = open(self.csv_path, "w", newline="")
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow(CSV_HEADER)
        self._start_dt = datetime.now()

    def write_sample(self, timestamp_us: int, seq: int, channel: int, gpio: int, adc: int):
        # Every row written here came from a frame that already passed CRC
        # validation in serial_reader.py — corrupted frames never reach this
        # point, so crc_ok is always 1 today. The column exists so a future
        # soft-fail mode (e.g. logging a frame despite a suspect CRC) has
        # somewhere to record that distinction without a schema change.
        self._csv_writer.writerow([timestamp_us, seq, channel, gpio, adc, 1])
        self.sample_count += 1

    def close(self, reader_stats, measured_rate_hz: float, jitter_stats: dict | None = None):
        self._csv_file.close()
        end_dt = datetime.now()
        actual_duration_s = (end_dt - self._start_dt).total_seconds()

        total_expected = self.sample_count + reader_stats.frames_dropped
        drop_rate_pct = (
            round(100.0 * reader_stats.frames_dropped / total_expected, 4)
            if total_expected > 0 else 0.0
        )

        meta_out = {
            "board": self.meta.board,
            "firmware": self.meta.firmware,
            "protocol_version": self.meta.protocol_version,
            "subject": self.meta.subject,
            "task": self.meta.task,
            "date": self._start_dt.strftime("%Y-%m-%d"),
            "start_time": self._start_dt.strftime("%H:%M:%S"),
            "end_time": end_dt.strftime("%H:%M:%S"),
            "actual_duration_s": round(actual_duration_s, 1),
            "nominal_sampling_rate_hz": self.meta.sampling_rate_hz,
            "measured_sampling_rate_hz": round(measured_rate_hz, 2),
            "adc_bits": self.meta.adc_bits,
            "adc_atten_db": self.meta.adc_atten_db,
            "channels": self.meta.channels,
            "reference_electrode": self.meta.reference_electrode,
            "calibration_method": self.meta.calibration_method,
            "calibration_gain": self.meta.calibration_gain,
            "total_samples": self.sample_count,
            "frames_ok": reader_stats.frames_ok,
            "frames_corrupted": reader_stats.frames_corrupted,
            "frames_dropped": reader_stats.frames_dropped,
            "gap_events": reader_stats.gap_events,
            "resyncs": reader_stats.resyncs,
            "drop_rate_pct": drop_rate_pct,
            "jitter": jitter_stats or {},
            "session_notes": self.meta.session_notes,
        }
        with open(self.meta_path, "w") as f:
            json.dump(meta_out, f, indent=2)

        log_lines = [
            f"Recording Started:      {meta_out['start_time']}",
            f"Recording Ended:        {meta_out['end_time']}",
            f"Actual Duration:        {actual_duration_s:.1f} s",
            f"Total Samples:         {self.sample_count}",
            f"Nominal Rate:           {self.meta.sampling_rate_hz} Hz",
            f"Measured Rate:          {measured_rate_hz:.2f} Hz",
            f"Frames OK:              {reader_stats.frames_ok}",
            f"Frames Corrupted:       {reader_stats.frames_corrupted}",
            f"Frames Dropped:         {reader_stats.frames_dropped} ({drop_rate_pct}%, {reader_stats.gap_events} gap event(s))",
            f"Resyncs:                {reader_stats.resyncs}",
            f"Calibration:            {self.meta.calibration_method} (gain={self.meta.calibration_gain})",
            f"CSV File:               {self.csv_path.name}",
        ]
        with open(self.log_path, "w") as f:
            f.write("\n".join(log_lines) + "\n")

        return meta_out
