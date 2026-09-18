/**
 * protocol.h
 *
 * Binary framed serial protocol for BioSignal-Recorder-v3.
 *
 * Every frame is: [0xAA 0x55] [type ...payload...] [CRC16].
 * The CRC16 covers everything between the sync bytes and the CRC itself
 * (i.e. type through the last payload byte) — never the sync bytes.
 *
 * CONFIG frame (sent once at boot, and again on host request via 'C'):
 *   [0xAA 0x55] [0x02] [proto_version u8] [n_channels u8]
 *   [sample_rate_hz u16 LE] [adc_bits u8] [adc_atten_db u8]
 *   n_channels x { [gpio u8] [label 8B ASCII] [selftest_ok u8] }
 *   [CRC16 u16 LE]
 *
 * SAMPLE frame (one per sample tick):
 *   [0xAA 0x55] [0x01] [n_channels u8]
 *   [seq u32 LE] [timestamp_us u64 LE]
 *   n_channels x [sample u16 LE]
 *   [CRC16 u16 LE]
 *
 * This layout is the single source of truth the host-side
 * recorder/bridge/protocol.py mirrors exactly — if you change the byte
 * layout here, update it there too.
 */

#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <Arduino.h>
#include <string.h>
#include "channels.h"

#define FRAME_SYNC_0       0xAA
#define FRAME_SYNC_1       0x55
#define FRAME_TYPE_SAMPLE  0x01
#define FRAME_TYPE_CONFIG  0x02
#define PROTOCOL_VERSION   1

// Max CONFIG frame size at MAX_CHANNELS=8: 2+1+1+1+2+1+1 + 8*(1+8+1) + 2 = 91B
// Max SAMPLE frame size at MAX_CHANNELS=8: 2+1+1+4+8 + 8*2 + 2 = 34B
#define FRAME_BUF_SIZE 128

// CRC16-CCITT (XModem): poly 0x1021, init 0x0000, no reflect, no final xor.
// Must stay byte-for-byte identical to recorder/bridge/protocol.py's crc16().
static uint16_t crc16_ccitt(const uint8_t *data, size_t len) {
  uint16_t crc = 0x0000;
  for (size_t i = 0; i < len; i++) {
    crc ^= (uint16_t)data[i] << 8;
    for (uint8_t bit = 0; bit < 8; bit++) {
      crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
  }
  return crc;
}

static inline void put_u16(uint8_t *buf, size_t *pos, uint16_t v) {
  buf[(*pos)++] = (uint8_t)(v & 0xFF);
  buf[(*pos)++] = (uint8_t)((v >> 8) & 0xFF);
}

static inline void put_u32(uint8_t *buf, size_t *pos, uint32_t v) {
  for (uint8_t i = 0; i < 4; i++) buf[(*pos)++] = (uint8_t)((v >> (8 * i)) & 0xFF);
}

static inline void put_u64(uint8_t *buf, size_t *pos, uint64_t v) {
  for (uint8_t i = 0; i < 8; i++) buf[(*pos)++] = (uint8_t)((v >> (8 * i)) & 0xFF);
}

// Encodes a SAMPLE frame into buf (must be >= FRAME_BUF_SIZE). Returns bytes written.
static size_t encode_sample_frame(uint8_t *buf, uint32_t seq, uint64_t timestamp_us,
                                   const uint16_t *values, uint8_t n_channels) {
  size_t pos = 0;
  buf[pos++] = FRAME_SYNC_0;
  buf[pos++] = FRAME_SYNC_1;
  size_t crc_start = pos;
  buf[pos++] = FRAME_TYPE_SAMPLE;
  buf[pos++] = n_channels;
  put_u32(buf, &pos, seq);
  put_u64(buf, &pos, timestamp_us);
  for (uint8_t i = 0; i < n_channels; i++) put_u16(buf, &pos, values[i]);
  uint16_t crc = crc16_ccitt(buf + crc_start, pos - crc_start);
  put_u16(buf, &pos, crc);
  return pos;
}

// Encodes a CONFIG frame for the channels referenced by active_idx[0..n_active).
// Returns bytes written.
static size_t encode_config_frame(uint8_t *buf, uint16_t sample_rate_hz, uint8_t adc_bits,
                                   uint8_t adc_atten_db, const Channel_t *channel_table,
                                   const uint8_t *active_idx, uint8_t n_active) {
  size_t pos = 0;
  buf[pos++] = FRAME_SYNC_0;
  buf[pos++] = FRAME_SYNC_1;
  size_t crc_start = pos;
  buf[pos++] = FRAME_TYPE_CONFIG;
  buf[pos++] = PROTOCOL_VERSION;
  buf[pos++] = n_active;
  put_u16(buf, &pos, sample_rate_hz);
  buf[pos++] = adc_bits;
  buf[pos++] = adc_atten_db;
  for (uint8_t i = 0; i < n_active; i++) {
    const Channel_t *ch = &channel_table[active_idx[i]];
    buf[pos++] = ch->gpio;
    memcpy(buf + pos, ch->label, 8);
    pos += 8;
    buf[pos++] = ch->selftest_ok ? 1 : 0;
  }
  uint16_t crc = crc16_ccitt(buf + crc_start, pos - crc_start);
  put_u16(buf, &pos, crc);
  return pos;
}

#endif
