#include <Arduino.h>
#include "synapse.h"

// ============================================================
// ESP32 EEG INPUT
// ============================================================
const int EEG_PIN = 35;

// EEG processing
synapse eeg_synapse;

// 250 Hz sampling
const uint32_t SAMPLE_INTERVAL_US = 4000;


// ============================================================
// SETUP
// ============================================================

void setup()
{
  Serial.begin(115200);

  // ESP32 ADC resolution: 12 bits (0-4095)
  analogReadResolution(12);

  // GPIO35 is input-only and is suitable for ADC input
  pinMode(EEG_PIN, INPUT);

  delay(1000);
}


// ============================================================
// LOOP
// ============================================================

void loop()
{
  // Read EEG ADC
  float rawSignal = analogRead(EEG_PIN);

  // DEBUG: raw-ADC test
  // apply_EEG_filters() is intentionally skipped while diagnosing
  // the ~21 Hz oscillation seen when the input is shorted.
  //
  // float filteredSignal = eeg_synapse.apply_EEG_filters(rawSignal);

  Serial.println(rawSignal);

  // Approximately 250 samples/second
  delayMicroseconds(SAMPLE_INTERVAL_US);
}
