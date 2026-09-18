#include <Arduino.h>
#include "synapse.h"

const int EXG_PIN = 34;

synapse exg_synapse;

void setup()
{
  Serial.begin(115200);

  pinMode(EXG_PIN, INPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(EXG_PIN, ADC_11db);
}

void loop()
{
  float rawSignal = analogRead(EXG_PIN);

  float filteredSignal =
    exg_synapse.apply_ECG_filters(rawSignal);
  Serial.println(filteredSignal);
  // Serial.println(rawSignal);

  delayMicroseconds(4000);   // ~250 samples/sec
}
