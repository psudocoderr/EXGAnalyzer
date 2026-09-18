import serial
import threading
import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
from scipy.signal import butter, filtfilt, spectrogram

# ============================================================
# Hardware & DSP Configuration
# ============================================================

COM_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200

# Kept generic -- the firmware pin assignment is the single source of truth
# (see EEG_PIN_CH1/EEG_PIN_CH2 in the .ino) and can change independently.
CHANNEL_LABELS = ('Ch1', 'Ch2')

# Only used to size buffers up front -- the firmware's delayMicroseconds(4000)
# loop doesn't guarantee exactly 250 Hz, so the real fs is measured each
# frame from sample arrival timestamps and used for filter design and the
# FFT/spectrogram frequency axes instead.
NOMINAL_FS = 250.0

# Rolling FFT history
WINDOW_SEC = 2.0
MAX_SAMPLES = int(NOMINAL_FS * WINDOW_SEC)


def estimate_fs(timestamps):
    """Measure the real sampling rate from sample arrival timestamps."""

    duration = timestamps[-1] - timestamps[0]

    if duration <= 0:
        return NOMINAL_FS

    return (len(timestamps) - 1) / duration

# Animation redraw interval (used below when building FuncAnimation)
ANIM_INTERVAL_MS = 150

# ============================================================
# Spectrogram Configuration
# ============================================================

SPEC_WINDOW_SEC = 2.0
SPEC_NPERSEG = int(NOMINAL_FS * SPEC_WINDOW_SEC)

# 75% overlap
SPEC_NOVERLAP = int(SPEC_NPERSEG * 0.75)

# Number of seconds of spectrogram history to display
SPEC_HISTORY_SEC = 10.0

# Frequency bins the spectrogram will use (fixed by SPEC_NPERSEG, using the
# nominal fs only to pick which bin index to cut off at -- the actual Hz
# labeling of those bins is refreshed each frame from the measured fs).
# Precomputed once so the rolling history buffers have a stable shape.
SPEC_FREQS_FULL = np.fft.rfftfreq(SPEC_NPERSEG, d=1.0 / NOMINAL_FS)
SPEC_FREQ_MASK = SPEC_FREQS_FULL <= 45.0
SPEC_FREQS = SPEC_FREQS_FULL[SPEC_FREQ_MASK]

# One history column per animation frame, covering SPEC_HISTORY_SEC total
SPEC_HISTORY_COLS = max(2, int(round(SPEC_HISTORY_SEC / (ANIM_INTERVAL_MS / 1000.0))))

# Rolling waterfall buffers: rows = frequency bins, columns = time history.
# One per channel. Each update() call shifts each buffer left by one column
# and appends the newest spectrogram slice, instead of redrawing a fresh
# snapshot every frame.
spec_history = [
    np.zeros((len(SPEC_FREQS), SPEC_HISTORY_COLS)),
    np.zeros((len(SPEC_FREQS), SPEC_HISTORY_COLS)),
]

# ============================================================
# Initialize Ring Buffer
# ============================================================

# Each entry is (arrival_timestamp, ch1_adc_value, ch2_adc_value)
raw_buffer = deque(maxlen=MAX_SAMPLES)

# Filters are (re)designed inside update() against the measured fs each
# frame, since the true sampling rate isn't guaranteed to be NOMINAL_FS.

# ============================================================
# Serial Reader Thread
# ============================================================

def serial_worker():

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

            if len(parts) < 2:
                print(f"Ignoring invalid data: {line}")
                continue

            # Store both channel values with their shared arrival time
            raw_buffer.append((time.time(), float(parts[0]), float(parts[1])))

        except ValueError:

            print(f"Ignoring invalid data: {line}")

        except Exception as e:

            print(f"Serial error: {e}")


# ============================================================
# Start Serial Thread
# ============================================================

thread = threading.Thread(
    target=serial_worker,
    daemon=True
)

thread.start()

# ============================================================
# Matplotlib GUI
# ============================================================

fig, axes = plt.subplots(
    3,
    2,
    figsize=(18, 10)
)

fig.canvas.manager.set_window_title(
    "Real-Time EEG Analyzer (2 Channels)"
)

raw_axes = (axes[0, 0], axes[0, 1])
fft_axes = (axes[1, 0], axes[1, 1])
spec_axes = (axes[2, 0], axes[2, 1])

# ============================================================
# Row 1 - Raw EEG
# ============================================================

line_raw = []

for ax, label in zip(raw_axes, CHANNEL_LABELS):

    ln, = ax.plot(
        [],
        [],
        color='#1f2937',
        lw=1.2
    )

    line_raw.append(ln)

    ax.set_xlim(0, WINDOW_SEC)
    ax.set_ylim(-0.2, 0.2)
    ax.set_title(f"{label} -- Raw Time Domain (DC Centered)")
    ax.set_xlabel("Time (Seconds)")
    ax.set_ylabel("Volts (V)")
    ax.grid(True, alpha=0.3)

# ============================================================
# Row 2 - FFT
# ============================================================

line_fft = []

for ax, label in zip(fft_axes, CHANNEL_LABELS):

    ln, = ax.plot(
        [],
        [],
        color='#3b82f6',
        lw=1.5
    )

    line_fft.append(ln)

    ax.set_xlim(0, 60)
    ax.set_ylim(0, 0.005)
    ax.set_title(f"{label} -- Filtered FFT (2.0-45 Hz Bandpass + 50 Hz Bandstop)")
    ax.set_xlabel("Frequency (Hz)")
    ax.set_ylabel("Magnitude (V)")
    ax.grid(True, alpha=0.3)

    # EEG bands
    ax.axvspan(0.5, 4, color='red', alpha=0.08, label='Delta')
    ax.axvspan(4, 8, color='orange', alpha=0.08, label='Theta')
    ax.axvspan(8, 13, color='green', alpha=0.08, label='Alpha')
    ax.axvspan(13, 30, color='blue', alpha=0.08, label='Beta')
    ax.axvspan(30, 45, color='purple', alpha=0.08, label='Gamma')
    ax.legend(loc='upper right', fontsize=8)

# ============================================================
# Row 3 - Spectrogram
# ============================================================

# Initial empty spectrograms, sized to the rolling history buffers

spec_image = []

for ax, label, history in zip(spec_axes, CHANNEL_LABELS, spec_history):

    img = ax.imshow(
        history,
        aspect='auto',
        origin='lower',
        extent=[
            -SPEC_HISTORY_SEC,
            0,
            SPEC_FREQS[0],
            SPEC_FREQS[-1]
        ],
        cmap='viridis'
    )

    spec_image.append(img)

    ax.set_ylim(0, 45)
    ax.set_xlim(-SPEC_HISTORY_SEC, 0)
    ax.set_title(f"{label} -- Real-Time Spectrogram")
    ax.set_xlabel("Time Relative to Now (Seconds)")
    ax.set_ylabel("Frequency (Hz)")

    fig.colorbar(img, ax=ax, label='Power')

# ============================================================
# Layout
# ============================================================

plt.tight_layout()

# ============================================================
# Per-Channel Processing Helper
# ============================================================

def process_channel(raw_arr, fs):
    """Convert ADC counts to centered volts and apply the notch+bandpass filters."""

    volts = (raw_arr / 4095.0) * 3.3

    volts_centered = volts - np.mean(volts)

    b_notch, a_notch = butter(4, [48.0, 52.0], btype='bandstop', fs=fs)
    b_bp, a_bp = butter(6, [2.0, 45.0], btype='bandpass', fs=fs)

    filtered = filtfilt(b_notch, a_notch, volts_centered)
    filtered = filtfilt(b_bp, a_bp, filtered)

    return volts_centered, filtered

# ============================================================
# Update Function
# ============================================================

def update(frame):

    # Need enough samples for the FFT/filter
    if len(raw_buffer) < MAX_SAMPLES:

        return (
            *line_raw,
            *line_fft,
            *spec_image
        )

    # --------------------------------------------------------
    # 1. Copy buffer, measure the real fs from arrival timestamps
    # --------------------------------------------------------

    buffered = list(raw_buffer)

    timestamps = np.array(
        [t for t, _, _ in buffered]
    )

    ch1_arr = np.array(
        [c1 for _, c1, _ in buffered]
    )

    ch2_arr = np.array(
        [c2 for _, _, c2 in buffered]
    )

    fs = estimate_fs(timestamps)

    time_axis = timestamps - timestamps[0]

    global spec_history

    # --------------------------------------------------------
    # 2. Process each channel independently
    # --------------------------------------------------------

    for idx, (raw_arr, raw_ax, fft_ax, spec_ax, r_line, f_line, s_image) in enumerate(zip(
        (ch1_arr, ch2_arr),
        raw_axes,
        fft_axes,
        spec_axes,
        line_raw,
        line_fft,
        spec_image
    )):

        # Convert to Volts, remove DC, filter (bandstop -> bandpass),
        # (re)designed against the measured fs
        volts_centered, filtered = process_channel(raw_arr, fs)

        # ====================================================
        # Update Raw Plot
        # ====================================================

        r_line.set_data(time_axis, volts_centered)

        raw_ax.set_xlim(time_axis[0], time_axis[-1])

        signal_min = np.min(volts_centered)
        signal_max = np.max(volts_centered)

        if signal_min != signal_max:

            margin = (signal_max - signal_min) * 0.2

            raw_ax.set_ylim(
                signal_min - margin,
                signal_max + margin
            )

        # ====================================================
        # Update FFT
        # ====================================================

        n = len(filtered)

        fft_mag = np.abs(np.fft.rfft(filtered)) / n
        freqs = np.fft.rfftfreq(n, d=1.0 / fs)

        f_line.set_data(freqs, fft_mag)

        fft_mask = (freqs >= 2.0) & (freqs <= 45.0)

        if np.any(fft_mask):
            max_fft = np.max(fft_mag[fft_mask])
        else:
            max_fft = 0.001

        fft_ax.set_ylim(0, max(0.001, max_fft * 1.2))

        # ====================================================
        # Spectrogram
        # ====================================================

        f_spec, t_spec, Sxx = spectrogram(
            filtered,
            fs=fs,
            nperseg=SPEC_NPERSEG,
            noverlap=SPEC_NOVERLAP,
            scaling='density',
            mode='psd'
        )

        # Keep only 0-45 Hz (same fixed bin indices as SPEC_FREQ_MASK, so
        # spec_history's shape stays stable frame to frame; f_spec's actual
        # Hz values still reflect the measured fs, used below)
        f_spec = f_spec[SPEC_FREQ_MASK]
        Sxx = Sxx[SPEC_FREQ_MASK, :]

        # Scroll the waterfall: drop the oldest column, append the newest
        # slice from this call's spectrogram (the most recent nperseg-sized
        # window). This is what gives the display SPEC_HISTORY_SEC seconds
        # of scrolling history, instead of redrawing a single snapshot.
        history = spec_history[idx]
        history[:, :-1] = history[:, 1:]
        history[:, -1] = Sxx[:, -1]

        s_image.set_data(history)
        s_image.set_extent([-SPEC_HISTORY_SEC, 0, f_spec[0], f_spec[-1]])

        if np.max(history) > 0:
            s_image.set_clim(vmin=np.max(history) * 0.001, vmax=np.max(history))

    return (
        *line_raw,
        *line_fft,
        *spec_image
    )


# ============================================================
# Animation
# ============================================================

ani = animation.FuncAnimation(
    fig,
    update,
    interval=ANIM_INTERVAL_MS,
    blit=False,
    cache_frame_data=False
)

plt.show()
