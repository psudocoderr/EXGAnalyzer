#include <Arduino.h>
#include "synapse.h"

// ============================================================
// nRF52840 EEG INPUT
// ============================================================
const int EEG_PIN = A0;

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
  analogReadResolution(12);
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

  // DEBUG: raw-ADC test to check whether the ~21Hz oscillation seen with
  // the input shorted comes from apply_EEG_filters() ringing or from the
  // ADC/analog front-end itself. apply_EEG_filters() is skipped for now
  // since its output isn't used while this raw-passthrough test is
  // active -- re-add the call below (and switch to
  // Serial.println(filteredSignal)) once this is diagnosed.
  // float filteredSignal = eeg_synapse.apply_EEG_filters(rawSignal);
  Serial.println(rawSignal);

  // Approximately 250 samples/second
  delayMicroseconds(SAMPLE_INTERVAL_US);
}
