import serial
import time
import csv
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import iirnotch, butter, filtfilt

# --- Configuration ---
COM_PORT = 'COM5'  # Update to your ESP32 port
BAUD_RATE = 115200
RECORD_SEC = 10    # Duration to collect data
CSV_FILENAME = 'fft_results.csv'

def collect_filter_and_plot():
    print(f"Connecting to {COM_PORT}...")
    try:
        ser = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)
    except serial.SerialException:
        print("Error: Could not open COM port.")
        return
        
    data = []
    start_time = time.time()
    
    print(f"Recording for {RECORD_SEC} seconds...")
    
    while (time.time() - start_time) < RECORD_SEC:
        try:
            line = ser.readline().decode('utf-8').strip()
            if "CH0:" in line:
                val_str = line.split("CH0:")[1].split(",")[0]
                data.append(int(val_str))
        except Exception:
            pass
            
    ser.close()
    
    # --- Signal Processing ---
    if not data:
        print("No data received.")
        return
        
    fs = len(data) / RECORD_SEC
    print(f"Collected {len(data)} samples. Effective Sampling Rate: {fs:.2f} Hz")
    
    # Convert 12-bit ADC counts to Volts and remove DC offset
    volts = (np.array(data) / 4095.0) * 3.3
    volts -= np.mean(volts)
    
    # 1. Notch Filter (50 Hz, Q=30)
    b_notch, a_notch = iirnotch(50.0, 30.0, fs)
    volts_notched = filtfilt(b_notch, a_notch, volts)
    
    # 2. Bandpass Filter (0.5 - 45 Hz, 4th-order Butterworth)
    b_bp, a_bp = butter(4, [0.5, 45.0], btype='bandpass', fs=fs)
    volts_filtered = filtfilt(b_bp, a_bp, volts_notched)
    
    # Compute FFT on the filtered signal
    n = len(volts_filtered)
    fft_vals = np.abs(np.fft.rfft(volts_filtered)) / n
    freqs = np.fft.rfftfreq(n, d=1.0/fs)
    
    # --- Save to CSV ---
    with open(CSV_FILENAME, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Frequency_Hz', 'Magnitude_V'])
        for f, m in zip(freqs, fft_vals):
            writer.writerow([f, m])
    print(f"FFT data successfully saved to {CSV_FILENAME}")
    
    # --- Plotting ---
    plt.figure(figsize=(12, 5))
    plt.plot(freqs, fft_vals, color='#1f2937', linewidth=1.2)
    
    plt.axvspan(0.5, 4, color='red', alpha=0.08, label='Delta (0.5-4 Hz)')
    plt.axvspan(4, 8, color='orange', alpha=0.08, label='Theta (4-8 Hz)')
    plt.axvspan(8, 13, color='green', alpha=0.08, label='Alpha (8-13 Hz)')
    plt.axvspan(13, 30, color='blue', alpha=0.08, label='Beta (13-30 Hz)')
    plt.axvspan(30, 45, color='purple', alpha=0.08, label='Gamma (30-45 Hz)')
    
    plt.xlim(0, 60)
    plt.title(f"Channel 0 FFT - O1 (fs={fs:.2f} Hz) - Filtered")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Magnitude (V)")
    plt.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=5, frameon=False)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    collect_filter_and_plot()