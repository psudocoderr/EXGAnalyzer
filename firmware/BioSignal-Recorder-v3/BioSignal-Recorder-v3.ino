/**
 * BioSignal-Recorder-v3.ino
 *
 * Serial-only firmware for the BioAmp EXG Pill on ESP32 (ADC1 channels
 * only, GPIO32-39). No WiFi, no filesystem — this firmware does one job:
 * deterministic multi-channel sampling, streamed over USB serial as a
 * binary framed protocol (protocol.h) that a host bridge validates with
 * a CRC16 and a monotonic sequence number.
 *
 * Channel selection lives in channels.h — enable/disable electrodes
 * there; nothing in this file needs to change to add a channel.
 *
 * Sampling runs on a FreeRTOS task pinned to core 0 with vTaskDelayUntil
 * for drift-free periodic timing, isolated from loop()'s serial I/O on
 * core 1. Each tick's esp_timer_get_time() timestamp (microseconds) is
 * captured once and shared across that tick's channel reads — reads
 * within a tick are still sequential (one SAR ADC), so treat same-tick
 * inter-channel timing as approximate, not simultaneous.
 *
 * Define PROTOCOL_TEXT_DEBUG to fall back to human-readable CSV lines
 * on Serial instead of the binary protocol, for bench bring-up with a
 * plain terminal. Never use it for real recording sessions.
 */

#define PROTOCOL_TEXT_DEBUG

#include "channels.h"
#include "protocol.h"

#define ONBOARD_LED   2
#define BAUD_RATE     115200

#define SAMPLE_RATE_HZ      250     // 250 Hz — standard EEG/EXG acquisition rate
#define SAMPLE_INTERVAL_MS  (1000 / SAMPLE_RATE_HZ)
#define ADC_BITS            12
#define ADC_ATTEN_DB        11

#define QUEUE_DEPTH  (SAMPLE_RATE_HZ * 4)   // ~4s buffer, absorbs loop()/USB jitter

typedef struct {
  uint32_t seq;
  uint64_t timestamp_us;
  uint16_t values[MAX_CHANNELS];
} TickSample_t;

QueueHandle_t sampleQueue   = NULL;
TaskHandle_t  adcTaskHandle = NULL;
uint32_t      g_seq         = 0;

uint8_t active_idx[MAX_CHANNELS];  // indices into channels[] that are enabled
uint8_t n_active = 0;

uint8_t frame_buf[FRAME_BUF_SIZE];

void build_active_list() {
  n_active = 0;
  for (uint8_t i = 0; i < NUM_CHANNELS_DEFINED; i++) {
    if (channels[i].enabled) {
      active_idx[n_active++] = i;
    }
  }
}

// Per-channel wiring-sanity self-test (adapted from v2's setup() self-test):
// N reads on each enabled channel, reporting min/max/avg. Flags a channel
// bad if it never leaves near-zero (no signal / bad ground) or never moves
// at all (floating pin, stuck ADC). Runs before the sampling task starts,
// so it never competes with the 250Hz tick for ADC access. Result feeds
// selftest_ok, which is surfaced in the CONFIG frame and printed by the
// host bridge (recorder/bridge/main.py) — this is the "confirm integrity"
// signal for wiring/hardware, distinct from the CRC16 + sequence checks
// that guard the serial transport itself.
void run_channel_selftest() {
  const int SELFTEST_READS = 50;
  const uint16_t SELFTEST_MAX_SWING = 3500;  // out of 4095 — near-full-scale swing in a quiet window means no reference, not real signal
  for (uint8_t i = 0; i < NUM_CHANNELS_DEFINED; i++) {
    if (!channels[i].enabled) {
      channels[i].selftest_ok = false;
      continue;
    }
    uint8_t gpio = channels[i].gpio;
    uint32_t sum = 0;
    uint16_t lo = 4095, hi = 0;
    for (int n = 0; n < SELFTEST_READS; n++) {
      uint16_t v = analogRead(gpio);
      sum += v;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
      delay(5);
    }
    uint16_t avg = sum / SELFTEST_READS;
    uint16_t swing = hi - lo;
    bool ok;
    Serial.printf("[ADC] %s (GPIO%d) self-test: min=%u max=%u avg=%u (%.3f V avg)\n",
                  channels[i].label, gpio, lo, hi, avg, avg * 3.3f / 4095.0f);
    if (hi < 10) {
      Serial.printf("[ADC] %s WARNING: all reads near 0 - check wiring/GND\n", channels[i].label);
      ok = false;
    } else if (lo == hi) {
      Serial.printf("[ADC] %s WARNING: values static - pin may be floating\n", channels[i].label);
      ok = false;
    } else if (swing > SELFTEST_MAX_SWING) {
      // A properly-contacted electrode has a stable DC bias with the real
      // signal riding on top of it — swing this large in a quiet 250ms
      // window means the input has no reference and is picking up ambient
      // interference rail-to-rail, not a wiring short. Most common cause:
      // electrode(s) not making skin contact yet at boot.
      Serial.printf("[ADC] %s WARNING: swing=%u — input floating / no skin contact / unreferenced\n",
                    channels[i].label, swing);
      ok = false;
    } else {
      Serial.printf("[ADC] %s OK\n", channels[i].label);
      ok = true;
    }
    channels[i].selftest_ok = ok;
  }
}

void send_config_frame() {
  size_t len = encode_config_frame(frame_buf, SAMPLE_RATE_HZ, ADC_BITS, ADC_ATTEN_DB,
                                    channels, active_idx, n_active);
  Serial.write(frame_buf, len);
}

// Core-0 sampling task: drift-free 250Hz tick via vTaskDelayUntil, isolated
// from core-1 serial I/O in loop(). Non-blocking queue send — if the queue
// is ever full (host can't keep up), the sample is dropped silently here,
// but that gap still shows up as a sequence gap on the host side.
void adcSampleTask(void* parameter) {
  TickType_t lastWake = xTaskGetTickCount();
  for (;;) {
    vTaskDelayUntil(&lastWake, pdMS_TO_TICKS(SAMPLE_INTERVAL_MS));

    TickSample_t s;
    s.timestamp_us = (uint64_t)esp_timer_get_time();
    s.seq = g_seq++;
    for (uint8_t i = 0; i < n_active; i++) {
      s.values[i] = (uint16_t)analogRead(channels[active_idx[i]].gpio);
    }
    xQueueSend(sampleQueue, &s, 0);
  }
}

void setup() {
  Serial.begin(BAUD_RATE);
  delay(300);

  pinMode(ONBOARD_LED, OUTPUT);
  digitalWrite(ONBOARD_LED, LOW);

  build_active_list();

  analogReadResolution(ADC_BITS);
  for (uint8_t i = 0; i < n_active; i++) {
    uint8_t gpio = channels[active_idx[i]].gpio;
    analogSetPinAttenuation(gpio, ADC_11db);
    pinMode(gpio, INPUT);
  }

  run_channel_selftest();

  sampleQueue = xQueueCreate(QUEUE_DEPTH, sizeof(TickSample_t));
  xTaskCreatePinnedToCore(adcSampleTask, "ADCSample", 4096, NULL, 3, &adcTaskHandle, 0);

#ifndef PROTOCOL_TEXT_DEBUG
  send_config_frame();
#else
  Serial.println("timestamp_us,seq,channel,gpio,adc");
  Serial.println("READY");
#endif

  digitalWrite(ONBOARD_LED, HIGH);
}

void loop() {
#ifndef PROTOCOL_TEXT_DEBUG
  // Host can request a CONFIG resend (e.g. on late attach) by writing 'C'.
  while (Serial.available()) {
    if (Serial.read() == 'C') {
      send_config_frame();
    }
  }
#endif

  TickSample_t s;
  while (xQueueReceive(sampleQueue, &s, 0) == pdTRUE) {
#ifndef PROTOCOL_TEXT_DEBUG
    size_t len = encode_sample_frame(frame_buf, s.seq, s.timestamp_us, s.values, n_active);
    Serial.write(frame_buf, len);
#else
    for (uint8_t i = 0; i < n_active; i++) {
      Serial.printf("%llu,%lu,%u,%u,%u\n",
                    (unsigned long long)s.timestamp_us,
                    (unsigned long)s.seq,
                    i,
                    channels[active_idx[i]].gpio,
                    s.values[i]);
    }
#endif
  }
}
