"""
calibration.py

Converts raw ADC counts to calibrated microvolt amplitude. Shared by the
live bridge (session.py) and the offline analyzer (analyze_eeg_dataset.py)
so both paths report the same numbers from one implementation.

IMPORTANT — read before trusting the output as "clinical-grade":
No signal generator has been used to measure this hardware's actual gain.
NOMINAL_GAIN below is the BioAmp EXG Pill's datasheet-nominal gain as
documented in this repo's README ("x2.4 MVpp, x1 MV gain"), not a
per-device measured value. Every session this produces is tagged
calibration_method="datasheet_nominal" in its metadata.json so this is
never silently presented as verified. See recorder/CALIBRATION_AND_LIMITATIONS.md.
"""

from __future__ import annotations

ADC_MAX_COUNTS = 4095.0   # 12-bit ADC full scale
ADC_REF_VOLTAGE = 3.3     # volts, ESP32 ADC with 11dB attenuation full-scale
NOMINAL_GAIN = 2.4        # BioAmp EXG Pill datasheet-nominal gain (unverified)
CALIBRATION_METHOD = "datasheet_nominal"


def adc_to_adc_volts(adc_counts: float) -> float:
    """Reverses only the ADC's digitization — NOT the analog front-end gain.
    Result is ADC-referred volts, not electrode-referred amplitude."""
    return adc_counts * (ADC_REF_VOLTAGE / ADC_MAX_COUNTS)


def estimate_dc_bias(adc_counts_series) -> float:
    """Per-session, per-channel DC bias estimate (mean ADC count). Op-amp
    offset drifts board-to-board and with temperature, so this is measured
    per recording rather than assumed at a fixed half-scale value."""
    values = list(adc_counts_series)
    if not values:
        return ADC_MAX_COUNTS / 2.0
    return sum(values) / len(values)


def raw_to_uV(adc_counts: float, dc_bias_counts: float, gain: float = NOMINAL_GAIN) -> float:
    """Raw ADC count -> calibrated microvolt amplitude at the electrode.

    V_electrode = (adc_counts_to_volts(adc) - adc_counts_to_volts(dc_bias)) / gain
    """
    v_signal = adc_to_adc_volts(adc_counts - dc_bias_counts)
    v_electrode = v_signal / gain
    return v_electrode * 1e6  # volts -> microvolts
