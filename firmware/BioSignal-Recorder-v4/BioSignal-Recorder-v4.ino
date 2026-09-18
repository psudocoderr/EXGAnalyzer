#include <Arduino.h>
#include <WiFi.h>

const char *SSID = "YOUR_WIFI_SSID";
const char *PASSWORD = "YOUR_WIFI_PASSWORD";

const int EEG_PIN = 33;
const int SAMPLE_RATE = 256; // Hz

void setup() {
  analogSetAttenuation(ADC_6db);
  analogReadResolution(12);
  
  // Initialize WiFi for data streaming
  WiFi.begin(SSID, PASSWORD);
}

void loop() {
  int rawSignal = analogRead(EEG_PIN);
  
  // Apply digital filtering
  float filtered = bandpassFilter(rawSignal, 8, 30); // Alpha/Beta bands
  
  // Stream via WebSocket
  sendToServer(filtered);
  
  delayMicroseconds(1000000 / SAMPLE_RATE);
}