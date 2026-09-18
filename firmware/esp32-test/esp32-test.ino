/*
 * ESP32 DevKit V1
 * ADC + BioAmp Diagnostic Tool
 *
 * Purpose:
 *   Determine whether low ADC readings are caused by:
 *     - ADC configuration
 *     - wiring/reference problems
 *     - BioAmp output level
 *     - excessive noise
 *     - clipping
 *     - missing signal variation
 *
 * ADC pins:
 *   GPIO32 = ADC1_CH4
 *   GPIO33 = ADC1_CH5
 *
 * Serial Monitor:
 *   115200 baud
 *
 * Commands:
 *
 *   1 = Floating/disconnected test
 *   2 = GND test
 *   3 = 3.3V test
 *   4 = BioAmp test
 *   5 = Live monitor
 *   6 = 10 second detailed capture
 *   7 = Compare GPIO32 vs GPIO33
 *   8 = ADC raw sweep
 *   9 = Print wiring instructions
 *   h = Help
 *
 * IMPORTANT:
 *   Never apply more than 3.3 V to the ESP32 ADC pin.
 */

#include <Arduino.h>

// ══════════════════════════════════════════════════════════════
// USER CONFIGURATION
// ══════════════════════════════════════════════════════════════

#define ADC_PIN_CH0 32
#define ADC_PIN_CH1 33

#define ADC_RESOLUTION 12

// ESP32 attenuation.
// 11 dB gives the widest useful input range on classic ESP32.
#define ADC_ATTENUATION ADC_11db

// Number of ADC readings used for each measurement.
#define OVERSAMPLES 16

// Number of samples used for statistics.
#define STAT_SAMPLES 1000

// Approximate ADC reference voltage.
// This is ONLY an estimate. ESP32 ADC calibration is not perfect.
#define ADC_REFERENCE_VOLTAGE 3.3

// ══════════════════════════════════════════════════════════════
// DATA STRUCTURE
// ══════════════════════════════════════════════════════════════

struct ADCStats {
  uint16_t minValue;
  uint16_t maxValue;

  float average;
  float rms;
  float standardDeviation;

  uint16_t peakToPeak;

  float averageVoltage;
  float minVoltage;
  float maxVoltage;
};

// ══════════════════════════════════════════════════════════════
// BASIC ADC READING
// ══════════════════════════════════════════════════════════════

uint16_t readADC(uint8_t pin) {

  uint32_t sum = 0;

  for (int i = 0; i < OVERSAMPLES; i++) {
    sum += analogRead(pin);
  }

  return sum / OVERSAMPLES;
}

// ══════════════════════════════════════════════════════════════
// ADC → APPROXIMATE VOLTAGE
// ══════════════════════════════════════════════════════════════

float adcToVoltage(uint16_t adc) {

  return ((float)adc / 4095.0f) * ADC_REFERENCE_VOLTAGE;
}

// ══════════════════════════════════════════════════════════════
// COLLECT STATISTICS
// ══════════════════════════════════════════════════════════════

ADCStats measureADC(uint8_t pin, uint32_t durationMs) {

  ADCStats stats;

  uint32_t start = millis();

  uint32_t count = 0;

  double sum = 0.0;
  double sumSquares = 0.0;

  uint16_t minVal = 4095;
  uint16_t maxVal = 0;

  while (millis() - start < durationMs) {

    uint16_t value = readADC(pin);

    if (value < minVal)
      minVal = value;

    if (value > maxVal)
      maxVal = value;

    sum += value;
    sumSquares += ((double)value * (double)value);

    count++;

    delay(1);
  }

  if (count == 0)
    count = 1;

  double mean = sum / count;

  double variance =
      (sumSquares / count) -
      (mean * mean);

  if (variance < 0)
    variance = 0;

  stats.minValue = minVal;
  stats.maxValue = maxVal;

  stats.average = mean;

  stats.rms = sqrt(sumSquares / count);

  stats.standardDeviation = sqrt(variance);

  stats.peakToPeak = maxVal - minVal;

  stats.averageVoltage =
      adcToVoltage((uint16_t)round(mean));

  stats.minVoltage =
      adcToVoltage(minVal);

  stats.maxVoltage =
      adcToVoltage(maxVal);

  return stats;
}

// ══════════════════════════════════════════════════════════════
// PRINT STATISTICS
// ══════════════════════════════════════════════════════════════

void printStats(const char* name, ADCStats s) {

  Serial.println();
  Serial.println("--------------------------------------------");
  Serial.print("Channel: ");
  Serial.println(name);
  Serial.println("--------------------------------------------");

  Serial.print("Average ADC       : ");
  Serial.println(s.average, 2);

  Serial.print("Minimum ADC       : ");
  Serial.println(s.minValue);

  Serial.print("Maximum ADC       : ");
  Serial.println(s.maxValue);

  Serial.print("Peak-to-Peak ADC   : ");
  Serial.println(s.peakToPeak);

  Serial.print("RMS ADC           : ");
  Serial.println(s.rms, 2);

  Serial.print("Std Dev ADC       : ");
  Serial.println(s.standardDeviation, 3);

  Serial.println();

  Serial.print("Approx Avg Voltage: ");
  Serial.print(s.averageVoltage, 4);
  Serial.println(" V");

  Serial.print("Approx Min Voltage: ");
  Serial.print(s.minVoltage, 4);
  Serial.println(" V");

  Serial.print("Approx Max Voltage: ");
  Serial.print(s.maxVoltage, 4);
  Serial.println(" V");

  Serial.println("--------------------------------------------");
}

// ══════════════════════════════════════════════════════════════
// INTERPRET RESULTS
// ══════════════════════════════════════════════════════════════

void interpretStats(ADCStats s) {

  Serial.println();
  Serial.println("INTERPRETATION");
  Serial.println("==============");

  // Ground
  if (s.average < 30) {

    Serial.println("[INFO] Signal is very close to 0 V.");
  }

  // Near bottom
  else if (s.average < 150) {

    Serial.println("[INFO] Very low ADC operating point.");
    Serial.println("       Check BioAmp bias/reference.");
  }

  // Low-mid range
  else if (s.average < 1000) {

    Serial.println("[INFO] ADC operating point is below mid-scale.");
    Serial.println("       This is NOT automatically a problem.");
  }

  // Around middle
  else if (s.average < 3000) {

    Serial.println("[INFO] ADC operating point is in a healthy-looking range.");
  }

  // Near top
  else {

    Serial.println("[WARNING] ADC operating point is very high.");
    Serial.println("          Possible saturation.");
  }

  // Peak-to-peak
  Serial.println();

  if (s.peakToPeak <= 2) {

    Serial.println("[WARNING] Almost no ADC variation detected.");
    Serial.println("          Possible flat signal, wiring problem,");
    Serial.println("          or very quiet analog output.");
  }

  else if (s.peakToPeak <= 10) {

    Serial.println("[INFO] Small signal variation.");
    Serial.println("       Could be normal for a quiet BioAmp output.");
  }

  else if (s.peakToPeak <= 100) {

    Serial.println("[INFO] Noticeable signal variation.");
  }

  else {

    Serial.println("[INFO] Large signal variation.");
  }

  // Clipping
  if (s.maxValue >= 4090) {

    Serial.println("[WARNING] ADC is clipping near 4095.");
  }

  if (s.minValue <= 5) {

    Serial.println("[WARNING] ADC is approaching 0.");
  }

  Serial.println();
}

// ══════════════════════════════════════════════════════════════
// TEST 1
// ══════════════════════════════════════════════════════════════

void testFloating() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("TEST 1: FLOATING / DISCONNECTED ADC");
  Serial.println("============================================");

  Serial.println();
  Serial.println("Disconnect EVERYTHING from GPIO32 and GPIO33.");
  Serial.println("Leave the pins electrically floating.");
  Serial.println();
  Serial.println("WARNING:");
  Serial.println("Floating inputs are expected to be unstable.");
  Serial.println("This test mainly confirms that the ADC is alive.");
  Serial.println();

  delay(2000);

  ADCStats s32 = measureADC(ADC_PIN_CH0, 3000);
  ADCStats s33 = measureADC(ADC_PIN_CH1, 3000);

  printStats("GPIO32", s32);
  printStats("GPIO33", s33);

  Serial.println();
  Serial.println("Expected:");
  Serial.println("Floating ADCs may jump around considerably.");
  Serial.println("That is NORMAL.");
}

// ══════════════════════════════════════════════════════════════
// TEST 2
// ══════════════════════════════════════════════════════════════

void testGround() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("TEST 2: ADC → GND");
  Serial.println("============================================");

  Serial.println();
  Serial.println("Connect:");
  Serial.println("GPIO32 → ESP32 GND");
  Serial.println("GPIO33 → ESP32 GND");
  Serial.println();

  Serial.println("Starting in 3 seconds...");
  delay(3000);

  ADCStats s32 = measureADC(ADC_PIN_CH0, 5000);
  ADCStats s33 = measureADC(ADC_PIN_CH1, 5000);

  printStats("GPIO32", s32);
  printStats("GPIO33", s33);

  Serial.println();
  Serial.println("EXPECTED RESULT");
  Serial.println("----------------");

  Serial.println("Both channels should be very close to ADC = 0.");

  if (s32.average < 20 && s33.average < 20) {

    Serial.println();
    Serial.println("[PASS] ADC ground test looks good.");
  }
  else {

    Serial.println();
    Serial.println("[CHECK] ADC does not appear to be near zero.");
    Serial.println("Check your GND connection.");
  }
}

// ══════════════════════════════════════════════════════════════
// TEST 3
// ══════════════════════════════════════════════════════════════

void test3V3() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("TEST 3: ADC → 3.3V");
  Serial.println("============================================");

  Serial.println();
  Serial.println("Connect:");
  Serial.println("GPIO32 → ESP32 3V3");
  Serial.println("GPIO33 → ESP32 3V3");
  Serial.println();

  Serial.println("WARNING:");
  Serial.println("ONLY connect to the ESP32 3V3 pin.");
  Serial.println("NEVER connect 5V to GPIO32/33.");
  Serial.println();

  Serial.println("Starting in 3 seconds...");
  delay(3000);

  ADCStats s32 = measureADC(ADC_PIN_CH0, 5000);
  ADCStats s33 = measureADC(ADC_PIN_CH1, 5000);

  printStats("GPIO32", s32);
  printStats("GPIO33", s33);

  Serial.println();
  Serial.println("EXPECTED RESULT");
  Serial.println("----------------");
  Serial.println("Both should be near the upper end of the ADC range.");
  Serial.println("Do NOT expect perfect 4095.");
}

// ══════════════════════════════════════════════════════════════
// TEST 4
// ══════════════════════════════════════════════════════════════

void testBioAmp() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("TEST 4: BIOAMP OUTPUT");
  Serial.println("============================================");

  Serial.println();
  Serial.println("CHECK WIRING:");
  Serial.println();
  Serial.println("BioAmp GND  → ESP32 GND");
  Serial.println("BioAmp OUT  → ESP32 GPIO32");
  Serial.println();
  Serial.println("If using a second output:");
  Serial.println("BioAmp OUT2 → ESP32 GPIO33");
  Serial.println();
  Serial.println("DO NOT connect an electrode directly to GPIO32.");
  Serial.println();

  Serial.println("Starting in 5 seconds...");
  delay(5000);

  Serial.println();
  Serial.println("Measuring BioAmp output...");
  Serial.println();

  ADCStats s32 = measureADC(ADC_PIN_CH0, 10000);

  printStats("BIOAMP → GPIO32", s32);

  interpretStats(s32);

  Serial.println();
  Serial.println("Now compare:");
  Serial.println("1. BioAmp powered, no electrodes");
  Serial.println("2. BioAmp powered, electrodes attached");
  Serial.println();
  Serial.println("The operating point may stay similar.");
  Serial.println("What we care about is whether the signal");
  Serial.println("variation changes.");
}

// ══════════════════════════════════════════════════════════════
// LIVE MONITOR
// ══════════════════════════════════════════════════════════════

void liveMonitor() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("LIVE ADC MONITOR");
  Serial.println("============================================");

  Serial.println();
  Serial.println("Press any key to stop.");
  Serial.println();

  uint32_t lastPrint = millis();

  while (true) {

    if (Serial.available()) {

      while (Serial.available())
        Serial.read();

      break;
    }

    uint16_t a0 = readADC(ADC_PIN_CH0);
    uint16_t a1 = readADC(ADC_PIN_CH1);

    float v0 = adcToVoltage(a0);
    float v1 = adcToVoltage(a1);

    if (millis() - lastPrint >= 100) {

      lastPrint = millis();

      Serial.print("CH0: ");
      Serial.print(a0);
      Serial.print(" (");
      Serial.print(v0, 3);
      Serial.print(" V)");

      Serial.print("    CH1: ");
      Serial.print(a1);
      Serial.print(" (");
      Serial.print(v1, 3);
      Serial.println(" V)");
    }
  }

  Serial.println();
  Serial.println("Live monitor stopped.");
}

// ══════════════════════════════════════════════════════════════
// DETAILED 10 SECOND CAPTURE
// ══════════════════════════════════════════════════════════════

void detailedCapture() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("10 SECOND DETAILED CAPTURE");
  Serial.println("============================================");

  Serial.println();
  Serial.println("Sampling GPIO32.");
  Serial.println("Press any key to abort.");
  Serial.println();

  const uint32_t duration = 10000;

  uint32_t start = millis();

  uint32_t count = 0;

  uint16_t minVal = 4095;
  uint16_t maxVal = 0;

  double sum = 0;
  double sumSquares = 0;

  uint32_t nextPrint = start + 1000;

  while (millis() - start < duration) {

    if (Serial.available()) {

      while (Serial.available())
        Serial.read();

      Serial.println("Capture aborted.");
      return;
    }

    uint16_t value = readADC(ADC_PIN_CH0);

    if (value < minVal)
      minVal = value;

    if (value > maxVal)
      maxVal = value;

    sum += value;
    sumSquares += ((double)value * value);

    count++;

    if (millis() >= nextPrint) {

      Serial.print(".");

      nextPrint += 1000;
    }

    delay(1);
  }

  double mean = sum / count;

  double variance =
      sumSquares / count -
      mean * mean;

  if (variance < 0)
    variance = 0;

  double sd = sqrt(variance);

  Serial.println();
  Serial.println();

  Serial.println("RESULT");
  Serial.println("======");

  Serial.print("Samples collected : ");
  Serial.println(count);

  Serial.print("Average           : ");
  Serial.println(mean, 3);

  Serial.print("Min               : ");
  Serial.println(minVal);

  Serial.print("Max               : ");
  Serial.println(maxVal);

  Serial.print("Peak-to-peak      : ");
  Serial.println(maxVal - minVal);

  Serial.print("Std deviation     : ");
  Serial.println(sd, 4);

  Serial.print("Approx voltage    : ");
  Serial.print(adcToVoltage((uint16_t)round(mean)), 5);
  Serial.println(" V");

  Serial.println();

  Serial.println("SIGNAL INTERPRETATION");
  Serial.println("=====================");

  if (sd < 1.0) {

    Serial.println("VERY FLAT");
    Serial.println("Almost no variation is present.");
  }
  else if (sd < 3.0) {

    Serial.println("LOW VARIATION");
  }
  else if (sd < 10.0) {

    Serial.println("MODERATE VARIATION");
  }
  else {

    Serial.println("HIGH VARIATION");
  }
}

// ══════════════════════════════════════════════════════════════
// COMPARE CHANNELS
// ══════════════════════════════════════════════════════════════

void compareChannels() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("GPIO32 vs GPIO33");
  Serial.println("============================================");

  Serial.println();
  Serial.println("Both channels will be measured for 10 seconds.");
  Serial.println();

  ADCStats s32 = measureADC(ADC_PIN_CH0, 5000);
  ADCStats s33 = measureADC(ADC_PIN_CH1, 5000);

  printStats("GPIO32", s32);
  printStats("GPIO33", s33);

  Serial.println();
  Serial.println("COMPARISON");
  Serial.println("===========");

  Serial.print("DC difference: ");
  Serial.println(fabs(s32.average - s33.average), 2);

  Serial.print("P-P difference: ");
  Serial.println(
      abs((int)s32.peakToPeak -
          (int)s33.peakToPeak)
  );

  Serial.println();
}

// ══════════════════════════════════════════════════════════════
// ADC RAW SWEEP
// ══════════════════════════════════════════════════════════════

void adcSweep() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("ADC RAW SWEEP");
  Serial.println("============================================");

  Serial.println();
  Serial.println("This prints 100 individual ADC readings.");
  Serial.println();

  for (int i = 0; i < 100; i++) {

    uint16_t a0 = analogRead(ADC_PIN_CH0);
    uint16_t a1 = analogRead(ADC_PIN_CH1);

    Serial.print(i);
    Serial.print(",");

    Serial.print(a0);
    Serial.print(",");

    Serial.println(a1);

    delay(20);
  }

  Serial.println();
  Serial.println("Sweep complete.");
}

// ══════════════════════════════════════════════════════════════
// WIRING GUIDE
// ══════════════════════════════════════════════════════════════

void printWiring() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("WIRING GUIDE");
  Serial.println("============================================");

  Serial.println();

  Serial.println("ESP32 DEVKIT R1");
  Serial.println("----------------");

  Serial.println("GPIO32 = ADC Channel 0");
  Serial.println("GPIO33 = ADC Channel 1");
  Serial.println("GND    = Analog ground/reference");
  Serial.println("3V3    = 3.3 V supply");

  Serial.println();

  Serial.println("GROUND TEST");
  Serial.println("-----------");
  Serial.println("GPIO32 ───── GND");
  Serial.println("GPIO33 ───── GND");

  Serial.println();

  Serial.println("3.3V TEST");
  Serial.println("---------");
  Serial.println("GPIO32 ───── 3V3");
  Serial.println("GPIO33 ───── 3V3");

  Serial.println();

  Serial.println("BIOAMP TEST");
  Serial.println("-----------");
  Serial.println("BioAmp GND ───── ESP32 GND");
  Serial.println("BioAmp OUT ───── ESP32 GPIO32");

  Serial.println();

  Serial.println("OPTIONAL SECOND CHANNEL");
  Serial.println("------------------------");
  Serial.println("BioAmp OUT2 ───── ESP32 GPIO33");

  Serial.println();

  Serial.println("IMPORTANT");
  Serial.println("---------");
  Serial.println("Never apply >3.3 V to an ESP32 ADC pin.");
  Serial.println("Never connect electrodes directly to GPIO32/33.");
  Serial.println("The BioAmp analog front end must be between");
  Serial.println("the electrodes and the ESP32 ADC.");
}

// ══════════════════════════════════════════════════════════════
// HELP
// ══════════════════════════════════════════════════════════════

void printHelp() {

  Serial.println();
  Serial.println("============================================");
  Serial.println("ESP32 BIOAMP / ADC DIAGNOSTIC");
  Serial.println("============================================");

  Serial.println();
  Serial.println("Commands:");

  Serial.println("1  Floating / disconnected");
  Serial.println("2  GPIO32/33 → GND");
  Serial.println("3  GPIO32/33 → 3.3V");
  Serial.println("4  BioAmp output test");
  Serial.println("5  Live ADC monitor");
  Serial.println("6  10-second detailed capture");
  Serial.println("7  Compare GPIO32 vs GPIO33");
  Serial.println("8  Raw ADC sweep");
  Serial.println("9  Wiring guide");
  Serial.println("h  Help");

  Serial.println();
}

// ══════════════════════════════════════════════════════════════
// SETUP
// ══════════════════════════════════════════════════════════════

void setup() {

  Serial.begin(115200);

  delay(1000);

  Serial.println();
  Serial.println();
  Serial.println("############################################");
  Serial.println("# ESP32 DevKit R1                         #");
  Serial.println("# BioAmp / ADC Diagnostic Tool            #");
  Serial.println("############################################");

  Serial.println();

  // Configure ADC
  analogReadResolution(ADC_RESOLUTION);

  analogSetPinAttenuation(
      ADC_PIN_CH0,
      ADC_ATTENUATION
  );

  analogSetPinAttenuation(
      ADC_PIN_CH1,
      ADC_ATTENUATION
  );

  pinMode(ADC_PIN_CH0, INPUT);
  pinMode(ADC_PIN_CH1, INPUT);

  Serial.println("ADC configuration:");
  Serial.println("Resolution : 12 bit");
  Serial.println("GPIO32     : ADC1");
  Serial.println("GPIO33     : ADC1");
  Serial.println("Attenuation: 11 dB");

  Serial.println();

  Serial.println("Approximate ADC scale:");
  Serial.println("0    → ~0 V");
  Serial.println("2048 → ~1.65 V");
  Serial.println("4095 → ~3.3 V");

  Serial.println();

  Serial.println("NOTE:");
  Serial.println("The voltage conversion above is approximate.");
  Serial.println("ESP32 ADC calibration/non-linearity means");
  Serial.println("raw ADC values are more trustworthy for");
  Serial.println("diagnosing the signal than the calculated voltage.");

  printHelp();
}

// ══════════════════════════════════════════════════════════════
// LOOP
// ══════════════════════════════════════════════════════════════

void loop() {

  if (!Serial.available()) {

    delay(20);
    return;
  }

  char command = Serial.read();

  // Remove remaining newline/carriage return
  while (Serial.available()) {

    char c = Serial.peek();

    if (c == '\n' || c == '\r')
      Serial.read();
    else
      break;
  }

  switch (command) {

    case '1':
      testFloating();
      break;

    case '2':
      testGround();
      break;

    case '3':
      test3V3();
      break;

    case '4':
      testBioAmp();
      break;

    case '5':
      liveMonitor();
      break;

    case '6':
      detailedCapture();
      break;

    case '7':
      compareChannels();
      break;

    case '8':
      adcSweep();
      break;

    case '9':
      printWiring();
      break;

    case 'h':
    case 'H':
      printHelp();
      break;

    default:
      Serial.println();
      Serial.print("Unknown command: ");
      Serial.println(command);
      Serial.println("Press 'h' for help.");
      break;
  }
}
