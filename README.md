# EXGAnalyzer

Low-cost biopotential (EEG / ECG / EMG / EOG) acquisition and analysis using the
[Upside Down Labs BioAmp EXG Pill](https://github.com/upsidedownlabs/BioAmp-EXG-Pill).
Firmware samples the analog front end and streams it over USB serial. Python tools
record and analyse the signal (filtering, FFT, spectrograms).

> **Experimental.** Research/educational project, not a medical device.

## Repository layout

Each commit on `main` is one self-contained version: the tree holds only that
version's firmware and scripts. Older versions are reachable via their tags
(`git checkout v3`).

| Path | Contents |
|------|----------|
| `firmware/BioSignal-Recorder-v7.5/` | Current sketch: single-channel EEG on ESP32 (GPIO35) at 250 Hz over serial, filtered with `synapse.h`. |
| `recorder/` | Python tools for the current version: `recorder.py` (capture to CSV), `analyzer.py` (offline filtering + FFT), `Live_EEG_viewer*.py`. |
| `data/` | Recorded sessions (gitignored, local only). See [data/README.md](data/README.md). |
| `docs/` | BioAmp EXG Pill datasheet, notes, third-party licenses. |
| `images/` | Example FFT results. |

### Versions

| Tag / branch | What it is |
|--------------|------------|
| `v1` | Upstream Upside Down Labs BioSignal-Recorder (WiFi + SPIFFS web UI) |
| `v2` | Own ESP32 WiFi/WebSocket recorder |
| `v3` | Serial-only multi-channel firmware, binary framed protocol + Python bridge |
| `v4`–`v6` | Simplified serial sampling, `synapse.h` filters, live viewer |
| `v7` | nRF52840 single-channel, recorder/analyzer split |
| `v7.5` | Same pipeline ported to ESP32 |
| branch `esp32-test` | ADC + BioAmp diagnostic sketch |
| branch `web/esp32-exg-ap-dashboard` | Self-hosted WiFi AP with a browser dashboard |

## Quick start

1. Flash `firmware/BioSignal-Recorder-v7.5/BioSignal-Recorder-v7.5.ino` to an ESP32
   (Arduino IDE / arduino-cli).
2. Install Python dependencies:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Record and analyse (sessions land in `data/v7.5/`):
   ```bash
   python recorder/recorder.py --port /dev/ttyUSB0 --duration 30
   python recorder/analyzer.py --csv data/v7.5/eeg_session_<timestamp>.csv
   ```

## Example results

| Eyes closed | Eyes open |
|---|---|
| ![Eyes closed](images/Eyes_Closed_both.png) | ![Eyes open](images/Eyes_Open_fft.png) |

## Safety

Only power the circuit from a battery or an isolated USB source (e.g. a laptop
running on battery). Never connect electrodes to a person while the device is
connected to mains-powered equipment.

## License

[MIT](LICENSE). `v1` is derived from
[upsidedownlabs/BioSignal-Recorder](https://github.com/upsidedownlabs/BioSignal-Recorder)
(MIT, see [docs/third-party/upsidedownlabs-LICENSE](docs/third-party/upsidedownlabs-LICENSE)).
