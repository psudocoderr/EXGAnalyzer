/**
 * channels.h
 *
 * Data-driven ADC channel table for BioSignal-Recorder-v3.
 *
 * To add/remove an electrode, edit the table below — nothing else in the
 * firmware needs to change. This replaces the old pattern of commenting
 * and uncommenting duplicated per-channel code blocks.
 *
 * ESP32 ADC1 exposes 8 usable pins (GPIO32-39); ADC2 is deliberately not
 * used (separate, independently documented nonlinearity issues, and no
 * benefit here since this firmware never enables WiFi).
 */

#ifndef CHANNELS_H
#define CHANNELS_H

#include <Arduino.h>

#define MAX_CHANNELS 8

typedef struct {
  uint8_t gpio;        // ADC1 GPIO pin (32-39)
  char    label[8];    // Electrode label, ASCII, null-padded (e.g. "O1", "FP1")
  bool    enabled;      // Whether this channel is sampled/transmitted
  bool    selftest_ok;  // Filled in by run_channel_selftest() at boot
} Channel_t;

// Phase 1: only O1 (GPIO32) enabled. Phase 2 flips FP1 (GPIO33) on.
// Add rows here (up to MAX_CHANNELS) for further electrodes.
static Channel_t channels[MAX_CHANNELS] = {
  { 32, "O1",  true,  false },
  { 33, "FP1", false, false },
};

// Number of table rows populated above (enabled or not) — distinct from
// how many are actually active, which is computed at boot.
static const uint8_t NUM_CHANNELS_DEFINED = 2;

#endif
