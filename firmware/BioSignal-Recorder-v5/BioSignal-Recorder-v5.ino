#include <Arduino.h>
#include "synapse.h"

// ============================================================
// BIO AMP EXG PILL
// ============================================================

// Use an ADC1 pin on ESP32
const int EXG_PIN = 34;

// Sampling frequency
const uint32_t SAMPLE_RATE = 250;

// Hardware timer
hw_timer_t *sampleTimer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;

volatile bool sampleReady = false;


// ============================================================
// TIMER INTERRUPT
// ============================================================

void IRAM_ATTR onSampleTimer()
{
  portENTER_CRITICAL_ISR(&timerMux);
  sampleReady = true;
  portEXIT_CRITICAL_ISR(&timerMux);
}


// ============================================================
// SYNAPSE FILTER
// ============================================================

synapse exg_synapse;


// ============================================================
// SETUP
// ============================================================

void setup()
{
  Serial.begin(115200);

  // Configure ADC
  pinMode(EXG_PIN, INPUT);

  analogReadResolution(12);       // ESP32 ADC: 0-4095
  analogSetPinAttenuation(
    EXG_PIN,
    ADC_11db
  );

  // ----------------------------------------------------------
  // ESP32 hardware timer
  //
  // Timer clock = 80 MHz / 80 = 1 MHz
  // Therefore:
  //
  // 1 tick = 1 microsecond
  //
  // 250 Hz = 4000 us
  // ----------------------------------------------------------

  sampleTimer = timerBegin(0, 80, true);

  timerAttachInterrupt(
    sampleTimer,
    &onSampleTimer,
    true
  );

  timerAlarmWrite(
    sampleTimer,
    4000,       // 4000 us = 250 Hz
    true
  );

  timerAlarmEnable(sampleTimer);
}


// ============================================================
// LOOP
// ============================================================

void loop()
{
  bool doSample = false;

  portENTER_CRITICAL(&timerMux);

  if (sampleReady)
  {
    sampleReady = false;
    doSample = true;
  }

  portEXIT_CRITICAL(&timerMux);


  if (doSample)
  {
    // Read BIO AMP EXG Pill
    float rawSignal = analogRead(EXG_PIN);

    // ECG filtering
    float filteredSignal =
      exg_synapse.apply_ECG_filters(rawSignal);

    // Send to Serial Plotter
    Serial.print(rawSignal);
    Serial.print(",");
    Serial.println(filteredSignal);
  }
}
