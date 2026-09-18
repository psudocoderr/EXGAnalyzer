import serial
import threading
import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
from scipy.signal import butter, filtfilt

# --- Hardware & DSP Configuration ---
COM_PORT = '/dev/ttyUSB0'        # Change to your ESP32 COM port
BAUD_RATE = 115200
NOMINAL_FS = 250.0       # Only used to size the buffer -- actual fs is measured from arrival timestamps,
                         # since the firmware's delayMicroseconds(4000) loop doesn't guarantee exactly 250 Hz.
WINDOW_SEC = 5.0         # Rolling history window for the raw/FFT view
MAX_SAMPLES = int(NOMINAL_FS * WINDOW_SEC)

# Kept generic -- the firmware pin assignment is the single source of truth
# (see EEG_PIN_CH1/EEG_PIN_CH2/EEG_PIN_CH3 in the .ino) and can change independently.
CHANNEL_LABELS = ('Ch1', 'Ch2', 'Ch3')

# --- Initialize Global Ring Buffer ---
# deque automatically pushes old data out when MAX_SAMPLES is reached.
# Each entry is (arrival_timestamp, ch1_adc_value, ch2_adc_value, ch3_adc_value)
# so the real sampling rate can be measured instead of assumed.
raw_buffer = deque(maxlen=MAX_SAMPLES)


def estimate_fs(timestamps: np.ndarray) -> float:
    """Measure the real sampling rate from sample arrival timestamps."""
    duration = timestamps[-1] - timestamps[0]
    if duration <= 0:
        return NOMINAL_FS
    return (len(timestamps) - 1) / duration

def serial_worker():
    """Read and print lines exactly as sent by the ESP32 (ch1,ch2 per line)."""
    try:
        ser = serial.Serial(
            COM_PORT,
            BAUD_RATE,
            timeout=1
        )
        print(f"Connected to {COM_PORT}. Acquiring data...")

    except serial.SerialException as e:
        print(f"Failed to connect to {COM_PORT}: {e}")
        return

    while True:
        try:
            line = ser.readline().decode(
                "utf-8",
                errors="ignore"
            ).strip()

            if not line:
                continue

            # Print exactly what the ESP32 sent
            print(line)

            parts = line.split(",")
            if len(parts) < 3:
                print(f"Ignoring invalid data: {line}")
                continue

            # Store all channel values with their shared arrival time
            raw_buffer.append((time.time(), float(parts[0]), float(parts[1]), float(parts[2])))

        except ValueError:
            # Ignore anything that isn't numeric
            print(f"Ignoring invalid data: {line}")

        except Exception as e:
            print(f"Serial error: {e}")

# --- Start Background Thread ---
thread = threading.Thread(target=serial_worker, daemon=True)
thread.start()

# --- Matplotlib GUI Setup ---
fig, axes = plt.subplots(2, 3, figsize=(18, 7))
(ax1_raw, ax2_raw, ax3_raw), (ax1_fft, ax2_fft, ax3_fft) = axes
fig.canvas.manager.set_window_title("Real-Time EEG Analyzer (3 Channels)")

raw_axes = (ax1_raw, ax2_raw, ax3_raw)
fft_axes = (ax1_fft, ax2_fft, ax3_fft)
line_raw = []
line_fft = []

for ax, label in zip(raw_axes, CHANNEL_LABELS):
    ln, = ax.plot([], [], color='#1f2937', lw=1.2)
    line_raw.append(ln)
    ax.set_xlim(0, WINDOW_SEC)
    ax.set_ylim(-0.2, 0.2)
    ax.set_title(f"{label} -- Raw Time Domain (DC Centered)")
    ax.set_xlabel("Time (Seconds)")
    ax.set_ylabel("Volts (V)")
    ax.grid(True, alpha=0.3)

for ax, label in zip(fft_axes, CHANNEL_LABELS):
    ln, = ax.plot([], [], color='#3b82f6', lw=1.5)
    line_fft.append(ln)
    ax.set_xlim(0, 60)
    ax.set_ylim(0, 0.005)  # Starting Y-limit, scales dynamically
    ax.set_title(f"{label} -- Filtered FFT (2.0-45 Hz Bandpass + 50Hz Bandstop)")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude (V)")
    ax.grid(True, alpha=0.3)

    # Draw EEG bands
    ax.axvspan(0.5, 4, color='red', alpha=0.08, label='Delta')
    ax.axvspan(4, 8, color='orange', alpha=0.08, label='Theta')
    ax.axvspan(8, 13, color='green', alpha=0.08, label='Alpha')
    ax.axvspan(13, 30, color='blue', alpha=0.08, label='Beta')
    ax.axvspan(30, 45, color='purple', alpha=0.08, label='Gamma')
    ax.legend(loc='upper right', fontsize=8)

plt.tight_layout()


def process_channel(raw_arr: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Convert ADC counts to centered volts, and separately apply the notch+bandpass filters.

    Returns (volts_centered, filtered): the raw DC-centered signal (shown in the
    top row) and the notch+bandpass-filtered signal (used for the FFT).
    """
    volts = (raw_arr / 4095.0) * 3.3
    volts_centered = volts - np.mean(volts)

    b_notch, a_notch = butter(4, [48.0, 52.0], btype='bandstop', fs=fs)
    b_bp, a_bp = butter(6, [2.0, 45.0], btype='bandpass', fs=fs)
    filtered = filtfilt(b_notch, a_notch, volts_centered)
    filtered = filtfilt(b_bp, a_bp, filtered)
    return volts_centered, filtered


def update(frame):
    """Called every 150ms by FuncAnimation to update the graphs."""
    if len(raw_buffer) < MAX_SAMPLES:
        return (*line_raw, *line_fft)

    # 1. Split buffer into timestamps/channel values, measure the real fs
    buffered = list(raw_buffer)
    timestamps = np.array([t for t, _, _, _ in buffered])
    ch1_arr = np.array([c1 for _, c1, _, _ in buffered])
    ch2_arr = np.array([c2 for _, _, c2, _ in buffered])
    ch3_arr = np.array([c3 for _, _, _, c3 in buffered])
    fs = estimate_fs(timestamps)
    time_axis = timestamps - timestamps[0]

    for ch_arr, raw_ax, fft_ax, r_line, f_line in zip(
        (ch1_arr, ch2_arr, ch3_arr), raw_axes, fft_axes, line_raw, line_fft
    ):
        # 2-3. Convert to Volts, remove DC, filter (bandstop -> bandpass),
        #      designed against the actually measured fs
        volts_centered, filtered = process_channel(ch_arr, fs)

        # 4. Compute FFT
        n = len(filtered)
        fft_mag = np.abs(np.fft.rfft(filtered)) / n
        freqs = np.fft.rfftfreq(n, d=1.0 / fs)

        # 5. Update plot data
        r_line.set_data(time_axis, volts_centered)
        f_line.set_data(freqs, fft_mag)

        # Dynamically scale axes to accommodate signal spikes and fs drift
        raw_ax.set_xlim(time_axis[0], time_axis[-1])
        raw_ax.set_ylim(np.min(volts_centered) * 1.2, np.max(volts_centered) * 1.2)
        max_fft = np.max(fft_mag[(freqs >= 2.0) & (freqs <= 45.0)]) if len(freqs) > 0 else 0.001
        fft_ax.set_ylim(0, max(0.001, max_fft * 1.2))

    return (*line_raw, *line_fft)

# Run the animation loop at ~6.6 FPS (150ms)
ani = animation.FuncAnimation(fig, update, interval=150, blit=False, cache_frame_data=False)
plt.show()
