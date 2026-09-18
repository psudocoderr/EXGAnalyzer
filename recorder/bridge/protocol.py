"""
Binary framed serial protocol — mirrors firmware/BioSignal-Recorder-v3/protocol.h
byte-for-byte. If you change the wire layout in one place, update the other.

Frame layout (all little-endian):
  [0xAA 0x55] [type ...payload...] [CRC16]
CRC16 covers everything between the sync bytes and the CRC itself.

CONFIG (type=0x02): proto_version u8, n_channels u8, sample_rate_hz u16,
  adc_bits u8, adc_atten_db u8, then n_channels x (gpio u8, label 8B ASCII,
  selftest_ok u8).

SAMPLE (type=0x01): n_channels u8, seq u32, timestamp_us u64,
  then n_channels x sample u16.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

FRAME_SYNC = bytes([0xAA, 0x55])
FRAME_TYPE_SAMPLE = 0x01
FRAME_TYPE_CONFIG = 0x02
PROTOCOL_VERSION = 1

CONFIG_HEADER_LEN = 7   # type + proto_version + n_channels + sample_rate_hz(2) + adc_bits + adc_atten_db
CONFIG_CHANNEL_LEN = 10  # gpio(1) + label(8) + selftest_ok(1)
SAMPLE_HEADER_LEN = 14   # type + n_channels + seq(4) + timestamp_us(8)
SAMPLE_VALUE_LEN = 2


class CrcMismatch(Exception):
    """Raised when a frame's CRC16 doesn't match its payload — treat as corruption."""


def crc16_ccitt(data: bytes) -> int:
    """CRC16-CCITT (XModem): poly 0x1021, init 0x0000, no reflect, no final xor.
    Must stay byte-for-byte identical to firmware protocol.h's crc16_ccitt()."""
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


@dataclass
class ChannelInfo:
    gpio: int
    label: str
    selftest_ok: bool


@dataclass
class ConfigFrame:
    proto_version: int
    sample_rate_hz: int
    adc_bits: int
    adc_atten_db: int
    channels: list[ChannelInfo] = field(default_factory=list)

    @property
    def n_channels(self) -> int:
        return len(self.channels)


@dataclass
class SampleFrame:
    seq: int
    timestamp_us: int
    values: list[int] = field(default_factory=list)

    @property
    def n_channels(self) -> int:
        return len(self.values)


def config_frame_length(n_channels: int) -> int:
    """Total frame length (sync..crc inclusive) for a CONFIG frame with n_channels."""
    return len(FRAME_SYNC) + CONFIG_HEADER_LEN + CONFIG_CHANNEL_LEN * n_channels + 2


def sample_frame_length(n_channels: int) -> int:
    """Total frame length (sync..crc inclusive) for a SAMPLE frame with n_channels."""
    return len(FRAME_SYNC) + SAMPLE_HEADER_LEN + SAMPLE_VALUE_LEN * n_channels + 2


def decode_frame(frame: bytes):
    """Decode one complete frame (sync bytes through CRC inclusive).

    Returns a (ConfigFrame | SampleFrame) instance. Raises CrcMismatch if the
    CRC doesn't match, or ValueError for an unrecognized/malformed frame.
    """
    if len(frame) < 2 or frame[0:2] != FRAME_SYNC:
        raise ValueError("frame missing sync bytes")

    payload = frame[2:-2]
    crc_received = struct.unpack_from("<H", frame, len(frame) - 2)[0]
    crc_computed = crc16_ccitt(payload)
    if crc_received != crc_computed:
        raise CrcMismatch(f"crc mismatch: got {crc_received:#06x}, expected {crc_computed:#06x}")

    frame_type = payload[0]
    if frame_type == FRAME_TYPE_CONFIG:
        return _decode_config_payload(payload)
    if frame_type == FRAME_TYPE_SAMPLE:
        return _decode_sample_payload(payload)
    raise ValueError(f"unknown frame type {frame_type:#04x}")


def _decode_config_payload(payload: bytes) -> ConfigFrame:
    proto_version, n_channels, sample_rate_hz, adc_bits, adc_atten_db = struct.unpack_from(
        "<BBHBB", payload, 1
    )
    channels = []
    offset = 1 + CONFIG_HEADER_LEN - 1  # position right after the fixed header
    for _ in range(n_channels):
        gpio = payload[offset]
        label_raw = payload[offset + 1: offset + 9]
        label = label_raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        selftest_ok = bool(payload[offset + 9])
        channels.append(ChannelInfo(gpio=gpio, label=label, selftest_ok=selftest_ok))
        offset += CONFIG_CHANNEL_LEN
    return ConfigFrame(
        proto_version=proto_version,
        sample_rate_hz=sample_rate_hz,
        adc_bits=adc_bits,
        adc_atten_db=adc_atten_db,
        channels=channels,
    )


def _decode_sample_payload(payload: bytes) -> SampleFrame:
    n_channels = payload[1]
    seq, timestamp_us = struct.unpack_from("<IQ", payload, 2)
    offset = 2 + 4 + 8
    values = list(struct.unpack_from(f"<{n_channels}H", payload, offset))
    return SampleFrame(seq=seq, timestamp_us=timestamp_us, values=values)
