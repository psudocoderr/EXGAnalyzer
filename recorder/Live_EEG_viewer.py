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
FS = 245.0               # Estimated sampling rate from your previous data
WINDOW_SEC = 2.0         # 2 seconds of rolling history for the FFT window
MAX_SAMPLES = int(FS * WINDOW_SEC)

# --- Initialize Global Ring Buffers ---
# deques automatically push old data out when MAX_SAMPLES is reached
raw_buffer = deque(maxlen=MAX_SAMPLES)

# --- Aggressive Filter Design ---
# 1. Bandstop (Reject 48-52 Hz completely to catch the drifting 49.1 Hz mains noise)
b_notch, a_notch = butter(4, [48.0, 52.0], btype='bandstop', fs=FS)
# 2. Bandpass (6th-order, raised to 2.0 Hz to aggressively kill Delta-band baseline wandering)
b_bp, a_bp = butter(6, [2.0, 45.0], btype='bandpass', fs=FS)

def serial_worker():
    """Background thread to read serial data continuously without blocking the UI."""
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
        print(f"Connected to {COM_PORT}. Acquiring data...")
    except serial.SerialException:
        print(f"Failed to connect to {COM_PORT}. Is the Serial Monitor closed?")
        return

    while True:
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if "CH0:" in line:
                # Print to terminal exactly as requested
                print(line)
                
                # Parse value and add to ring buffer
                val_str = line.split("CH0:")[1].split(",")[0]
                raw_buffer.append(int(val_str))
        except Exception:
            pass

# --- Start Background Thread ---
thread = threading.Thread(target=serial_worker, daemon=True)
thread.start()

# --- Matplotlib GUI Setup ---
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7))
fig.canvas.manager.set_window_title("Real-Time EEG Analyzer")

# Graph 1: Raw Data Line
line_raw, = ax1.plot([], [], color='#1f2937', lw=1.2)
ax1.set_xlim(0, WINDOW_SEC)
ax1.set_ylim(-0.2, 0.2)
ax1.set_title("Raw Time Domain (DC Centered)")
ax1.set_xlabel("Time (Seconds)")
ax1.set_ylabel("Volts (V)")
ax1.grid(True, alpha=0.3)

# Graph 2: FFT Line
line_fft, = ax2.plot([], [], color='#3b82f6', lw=1.5)
ax2.set_xlim(0, 60)
ax2.set_ylim(0, 0.005) # Starting Y-limit, scales dynamically
ax2.set_title("Filtered FFT (2.0 - 45 Hz Bandpass + 50Hz Bandstop)")
ax2.set_xlabel("Frequency (Hz)")
ax2.set_ylabel("Magnitude (V)")
ax2.grid(True, alpha=0.3)

# Draw EEG Bands
ax2.axvspan(0.5, 4, color='red', alpha=0.08, label='Delta')
ax2.axvspan(4, 8, color='orange', alpha=0.08, label='Theta')
ax2.axvspan(8, 13, color='green', alpha=0.08, label='Alpha')
ax2.axvspan(13, 30, color='blue', alpha=0.08, label='Beta')
ax2.axvspan(30, 45, color='purple', alpha=0.08, label='Gamma')
ax2.legend(loc='upper right')

plt.tight_layout()

def update(frame):
    """Called every 150ms by FuncAnimation to update the graphs."""
    if len(raw_buffer) < MAX_SAMPLES:
        return line_raw, line_fft
    
    # 1. Convert to Volts and remove DC offset
    raw_arr = np.array(raw_buffer)
    volts = (raw_arr / 4095.0) * 3.3
    volts_centered = volts - np.mean(volts)
    
    # 2. Apply Filters (Bandstop -> Bandpass)
    filtered = filtfilt(b_notch, a_notch, volts_centered)
    filtered = filtfilt(b_bp, a_bp, filtered)
    
    # 3. Compute FFT
    n = len(filtered)
    fft_mag = np.abs(np.fft.rfft(filtered)) / n
    freqs = np.fft.rfftfreq(n, d=1.0/FS)
    
    # 4. Update Plot Data
    time_axis = np.linspace(0, WINDOW_SEC, len(volts_centered))
    line_raw.set_data(time_axis, volts_centered)
    line_fft.set_data(freqs, fft_mag)
    
    # Dynamically scale Y-axes to accommodate signal spikes
    ax1.set_ylim(np.min(volts_centered)*1.2, np.max(volts_centered)*1.2)
    max_fft = np.max(fft_mag[(freqs >= 2.0) & (freqs <= 45.0)]) if len(freqs) > 0 else 0.001
    ax2.set_ylim(0, max(0.001, max_fft * 1.2))
    
    return line_raw, line_fft

# Run the animation loop at ~6.6 FPS (150ms)
ani = animation.FuncAnimation(fig, update, interval=150, blit=False, cache_frame_data=False)
plt.show()
