# data/

Recorded sessions live here, **locally only**. Everything in this folder except
this README is gitignored: recordings are personal/subject data, not source.

## Layout

| Path | Written by | Contents |
|------|------------|----------|
| `data/EEG_Dataset/<Subject>/<Date>/<Task>/` | v2/v3 recorders (`eegrecorder-*.py`, `bridge/`) | Raw CSV runs + metadata. These scripts use `./EEG_Dataset` relative to the working directory, so run them from `data/`. |
| `data/v7/`, `data/v7.5/` | `recorder/recorder.py` | `eeg_session_<YYYYMMDD_HHMMSS>.csv` (+ `.png` from `analyzer.py`) |

Subfolders under a version (per subject, per test, per day) are free-form.

## CSV format (v7, v7.5)

```
elapsed_s,value
0.0,546.0
```

`elapsed_s` is seconds since the recording started, `value` is the raw 12-bit ADC reading (0-4095).
