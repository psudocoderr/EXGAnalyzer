"""
serial_reader.py

Reads raw bytes from the ESP32 over USB serial, resyncs on the 0xAA 0x55
frame marker (see protocol.py), and yields decoded CONFIG/SAMPLE frames
while tracking frame-level integrity counters that are kept distinct from
each other on purpose — loss and corruption are different failure modes:

  frames_ok         - frames successfully decoded (CRC passed)
  frames_corrupted  - frames whose CRC failed (bytes arrived, but were wrong)
  frames_dropped    - samples inferred missing from SAMPLE seq gaps
  gap_events        - number of distinct gaps (not total dropped samples)
  resyncs           - times the byte scanner had to skip forward looking
                       for the next valid frame start
  bytes_discarded   - raw bytes skipped while resyncing (includes ESP32
                       boot-time bootloader noise on first connect)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import serial

from . import protocol

MAX_CHANNELS = 8


@dataclass
class ReaderStats:
    frames_ok: int = 0
    frames_corrupted: int = 0
    frames_dropped: int = 0
    gap_events: int = 0
    resyncs: int = 0
    bytes_discarded: int = 0


class SerialFrameReader:
    """Wraps a pyserial connection, decoding the binary frame protocol."""

    def __init__(self, port: str, baud: int = 921600, timeout: float = 1.0):
        self.port_name = port
        self.baud = baud
        self.timeout = timeout
        self.ser: serial.Serial | None = None
        self.buf = bytearray()
        self.stats = ReaderStats()
        self._last_seq: int | None = None

    def open(self):
        self.ser = serial.Serial(self.port_name, self.baud, timeout=self.timeout)
        # Reset the ESP32 by toggling DTR; boot-time bootloader text that
        # follows is just noise the frame scanner resyncs past below — no
        # magic string handshake needed, unlike the old text protocol.
        self.ser.setDTR(False)
        time.sleep(0.1)
        self.ser.setDTR(True)
        self.ser.reset_input_buffer()
        self.buf.clear()

    def close(self):
        if self.ser is not None:
            self.ser.close()
            self.ser = None

    def wait_for_config(self, timeout_s: float = 10.0) -> protocol.ConfigFrame:
        """Blocks until a valid CONFIG frame is decoded, or raises TimeoutError."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            for frame in self._poll():
                if isinstance(frame, protocol.ConfigFrame):
                    return frame
        raise TimeoutError("no CONFIG frame received within timeout")

    def request_config(self):
        """Ask the firmware to re-send its CONFIG frame (e.g. late attach)."""
        if self.ser is not None:
            self.ser.write(b"C")

    def stream_samples(self):
        """Generator yielding SampleFrame instances as they arrive, until the
        serial connection is closed or raises."""
        while True:
            for frame in self._poll():
                if isinstance(frame, protocol.SampleFrame):
                    self._track_sequence(frame)
                    yield frame
                # A ConfigFrame arriving mid-stream (e.g. a requested resend)
                # is just dropped here — callers needing it use wait_for_config.

    def _track_sequence(self, frame: protocol.SampleFrame):
        if self._last_seq is not None:
            gap = frame.seq - self._last_seq - 1
            if gap > 0:
                self.stats.frames_dropped += gap
                self.stats.gap_events += 1
            # gap < 0 (seq went backwards, e.g. firmware rebooted mid-session)
            # is not counted as negative drops — just resynchronize silently.
        self._last_seq = frame.seq

    def _poll(self):
        """Reads available bytes and extracts as many complete frames as
        possible from the buffer, returning a list of decoded frames."""
        chunk = self.ser.read(4096)
        if chunk:
            self.buf.extend(chunk)

        frames = []
        while True:
            frame = self._try_extract_one()
            if frame is None:
                break
            frames.append(frame)
        return frames

    def _try_extract_one(self):
        buf = self.buf
        sync_pos = buf.find(protocol.FRAME_SYNC)
        if sync_pos == -1:
            # Keep only the last byte in case it's half of a split sync marker.
            if len(buf) > 1:
                self.stats.bytes_discarded += len(buf) - 1
                del buf[:-1]
            return None

        if sync_pos > 0:
            self.stats.bytes_discarded += sync_pos
            del buf[:sync_pos]

        if len(buf) < 3:
            return None  # have sync, but not the type byte yet
        frame_type = buf[2]

        if frame_type == protocol.FRAME_TYPE_SAMPLE:
            if len(buf) < 4:
                return None
            n_channels = buf[3]
            if n_channels > MAX_CHANNELS:
                return self._resync_one_byte()
            total_len = protocol.sample_frame_length(n_channels)
        elif frame_type == protocol.FRAME_TYPE_CONFIG:
            if len(buf) < 5:
                return None
            n_channels = buf[4]
            if n_channels > MAX_CHANNELS:
                return self._resync_one_byte()
            total_len = protocol.config_frame_length(n_channels)
        else:
            return self._resync_one_byte()

        if len(buf) < total_len:
            return None  # wait for more bytes

        raw_frame = bytes(buf[:total_len])
        try:
            decoded = protocol.decode_frame(raw_frame)
        except protocol.CrcMismatch:
            self.stats.frames_corrupted += 1
            return self._resync_one_byte()
        except ValueError:
            return self._resync_one_byte()

        del buf[:total_len]
        self.stats.frames_ok += 1
        return decoded

    def _resync_one_byte(self):
        # A "sync-looking" byte pair turned out not to lead to a valid frame.
        # Drop just the first byte and let the next _try_extract_one() call
        # re-scan for the next 0xAA 0x55 — robust against a stray 0xAA 0x55
        # occurring inside otherwise-garbage bytes.
        self.stats.resyncs += 1
        del self.buf[:1]
        return None
