#include <Arduino.h>
#include "synapse.h"

// ============================================================
// ESP32 THREE-CHANNEL BIOSIGNAL INPUT
// ============================================================
const int EEG_PIN_CH1 = 33;  // ADC1_CH5
const int EEG_PIN_CH2 = 35;  // ADC1_CH4 (has internal pullups, unlike GPIO34-39)
const int EEG_PIN_CH3 = 34;  // ADC1_CH7 (input-only, no internal pullups)

// EEG processing -- one filter instance per channel so their IIR state
// (bp_z*/notch_z* in synapse.h) doesn't get mixed between channels
synapse eeg_synapse_ch1;
synapse eeg_synapse_ch2;
synapse eeg_synapse_ch3;

// 250 Hz sampling, all channels read per cycle
const uint32_t SAMPLE_INTERVAL_US = 4000;


// ============================================================
// SETUP
// ============================================================

void setup()
{
  Serial.begin(115200);
  analogReadResolution(12);
  pinMode(EEG_PIN_CH1, INPUT);
  pinMode(EEG_PIN_CH2, INPUT);
  pinMode(EEG_PIN_CH3, INPUT);

  delay(1000);
}


// ============================================================
// LOOP
// ============================================================

void loop()
{
  // Read all channels' ADCs
  float rawCh1 = analogRead(EEG_PIN_CH1);
  float rawCh2 = analogRead(EEG_PIN_CH2);
  float rawCh3 = analogRead(EEG_PIN_CH3);

  // DEBUG: raw-ADC test to check whether the ~21Hz oscillation seen with
  // the input shorted comes from apply_EEG_filters() ringing or from the
  // ADC/analog front-end itself. apply_EEG_filters() is skipped for now
  // since its output isn't used while this raw-passthrough test is
  // active -- re-add the calls below (and switch to the filtered
  // variables) once this is diagnosed.
  // float filteredCh1 = eeg_synapse_ch1.apply_EEG_filters(rawCh1);
  // float filteredCh2 = eeg_synapse_ch2.apply_EEG_filters(rawCh2);
  // float filteredCh3 = eeg_synapse_ch3.apply_EEG_filters(rawCh3);
  Serial.print(rawCh1);
  Serial.print(",");
  Serial.print(rawCh2);
  Serial.print(",");
  Serial.println(rawCh3);

  // Approximately 250 samples/second, per channel
  delayMicroseconds(SAMPLE_INTERVAL_US);
}
