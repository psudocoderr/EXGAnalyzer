#ifndef SYNAPSE_H
#define SYNAPSE_H

#include <Arduino.h>
#include <math.h>

class synapse
{
public:
  // ============================================================
  // EEG BAND-PASS FILTER
  // Sampling rate: 250 Hz
  // Passband: 0.5 - 40.5 Hz
  // ============================================================
  float eeg_filter(float input)
  {
    float output = input;

    // Section 1
    {
      float x = output
                - (-0.60733220f * bp_z1_1)
                - (0.12650924f * bp_z2_1);

      output = 0.02287021f * x
             + 0.04574042f * bp_z1_1
             + 0.02287021f * bp_z2_1;

      bp_z2_1 = bp_z1_1;
      bp_z1_1 = x;
    }

    // Section 2
    {
      float x = output
                - (-0.79989305f * bp_z1_2)
                - (0.51645386f * bp_z2_2);

      output = x
             + 2.0f * bp_z1_2
             + bp_z2_2;

      bp_z2_2 = bp_z1_2;
      bp_z1_2 = x;
    }

    // Section 3
    {
      float x = output
                - (-1.97652009f * bp_z1_3)
                - (0.97668236f * bp_z2_3);

      output = x
             - 2.0f * bp_z1_3
             + bp_z2_3;

      bp_z2_3 = bp_z1_3;
      bp_z1_3 = x;
    }

    // Section 4
    {
      float x = output
                - (-1.99042357f * bp_z1_4)
                - (0.99058175f * bp_z2_4);

      output = x
             - 2.0f * bp_z1_4
             + bp_z2_4;

      bp_z2_4 = bp_z1_4;
      bp_z1_4 = x;
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
      float x = output
                - (-0.58621390f * notch_z1_1)
                - (0.95447062f * notch_z2_1);

      output = 0.93642755f * x
             - 0.57892689f * notch_z1_1
             + 0.93642755f * notch_z2_1;

      notch_z2_1 = notch_z1_1;
      notch_z1_1 = x;
    }

    // Section 2
    {
      float x = output
                - (-0.62207340f * notch_z1_2)
                - (0.95474810f * notch_z2_2);

      output = x
             - 0.61822923f * notch_z1_2
             + notch_z2_2;

      notch_z2_2 = notch_z1_2;
      notch_z1_2 = x;
    }

    // Section 3
    {
      float x = output
                - (-0.56822557f * notch_z1_3)
                - (0.98081132f * notch_z2_3);

      output = x
             - 0.61822923f * notch_z1_3
             + notch_z2_3;

      notch_z2_3 = notch_z1_3;
      notch_z1_3 = x;
    }

    // Section 4
    {
      float x = output
                - (-0.65580392f * notch_z1_4)
                - (0.98109606f * notch_z2_4);

      output = x
             - 0.61822923f * notch_z1_4
             + notch_z2_4;

      notch_z2_4 = notch_z1_4;
      notch_z1_4 = x;
    }

    return output;
  }


  // ============================================================
  // EEG PROCESSING PIPELINE
  // ============================================================

  float apply_EEG_filters(float input_signal)
  {
    float filtered = eeg_filter(input_signal);

    filtered = remove_AC_noise(filtered);

    return filtered;
  }

private:
  // Per-instance IIR state (bandpass), one z1/z2 pair per biquad section
  float bp_z1_1 = 0.0f, bp_z2_1 = 0.0f;
  float bp_z1_2 = 0.0f, bp_z2_2 = 0.0f;
  float bp_z1_3 = 0.0f, bp_z2_3 = 0.0f;
  float bp_z1_4 = 0.0f, bp_z2_4 = 0.0f;

  // Per-instance IIR state (notch), one z1/z2 pair per biquad section
  float notch_z1_1 = 0.0f, notch_z2_1 = 0.0f;
  float notch_z1_2 = 0.0f, notch_z2_2 = 0.0f;
  float notch_z1_3 = 0.0f, notch_z2_3 = 0.0f;
  float notch_z1_4 = 0.0f, notch_z2_4 = 0.0f;
};

#endif