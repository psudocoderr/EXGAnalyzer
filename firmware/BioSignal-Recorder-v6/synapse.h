#ifndef SYNAPSE_H
#define SYNAPSE_H

#include <Arduino.h>
#include <math.h>

class synapse
{
public:

  // ============================================================
  // ECG BAND-PASS FILTER
  // Sampling rate: 250 Hz
  // Passband: 0.5 - 40.5 Hz
  // ============================================================

  float ecg_filter(float input)
  {
    float output = input;

    // Section 1
    {
      static float z1 = 0.0f;
      static float z2 = 0.0f;

      float x = output
                - (-0.60733220f * z1)
                - (0.12650924f * z2);

      output = 0.02287021f * x
             + 0.04574042f * z1
             + 0.02287021f * z2;

      z2 = z1;
      z1 = x;
    }

    // Section 2
    {
      static float z1 = 0.0f;
      static float z2 = 0.0f;

      float x = output
                - (-0.79989305f * z1)
                - (0.51645386f * z2);

      output = x
             + 2.0f * z1
             + z2;

      z2 = z1;
      z1 = x;
    }

    // Section 3
    {
      static float z1 = 0.0f;
      static float z2 = 0.0f;

      float x = output
                - (-1.97652009f * z1)
                - (0.97668236f * z2);

      output = x
             - 2.0f * z1
             + z2;

      z2 = z1;
      z1 = x;
    }

    // Section 4
    {
      static float z1 = 0.0f;
      static float z2 = 0.0f;

      float x = output
                - (-1.99042357f * z1)
                - (0.99058175f * z2);

      output = x
             - 2.0f * z1
             + z2;

      z2 = z1;
      z1 = x;
    }

    return output;
  }


  // ============================================================
  // 50 Hz NOTCH FILTER
  // Sampling rate: 250 Hz
  // Rejects mains interference around 50 Hz
  // ============================================================

  float remove_AC_noise(float input)
  {
    float output = input;

    // Section 1
    {
      static float z1 = 0.0f;
      static float z2 = 0.0f;

      float x = output
                - (-0.58621390f * z1)
                - (0.95447062f * z2);

      output = 0.93642755f * x
             - 0.57892689f * z1
             + 0.93642755f * z2;

      z2 = z1;
      z1 = x;
    }

    // Section 2
    {
      static float z1 = 0.0f;
      static float z2 = 0.0f;

      float x = output
                - (-0.62207340f * z1)
                - (0.95474810f * z2);

      output = x
             - 0.61822923f * z1
             + z2;

      z2 = z1;
      z1 = x;
    }

    // Section 3
    {
      static float z1 = 0.0f;
      static float z2 = 0.0f;

      float x = output
                - (-0.56822557f * z1)
                - (0.98081132f * z2);

      output = x
             - 0.61822923f * z1
             + z2;

      z2 = z1;
      z1 = x;
    }

    // Section 4
    {
      static float z1 = 0.0f;
      static float z2 = 0.0f;

      float x = output
                - (-0.65580392f * z1)
                - (0.98109606f * z2);

      output = x
             - 0.61822923f * z1
             + z2;

      z2 = z1;
      z1 = x;
    }

    return output;
  }


  // ============================================================
  // ECG PROCESSING PIPELINE
  // ============================================================

  float apply_ECG_filters(float input_signal)
  {
    float filtered = ecg_filter(input_signal);

    filtered = remove_AC_noise(filtered);

    return filtered;
  }
};

#endif

                