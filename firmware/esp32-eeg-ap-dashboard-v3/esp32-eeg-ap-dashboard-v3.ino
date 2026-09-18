/**
 * esp32-eeg-ap-dashboard-v3.ino
 *
 * Generic 12-bit-ADC board + amplifier  ->  self-hosted WiFi AP  ->  browser
 *
 * Single global loop, single ADC pin -- no FreeRTOS tasks/queues, no NVS,
 * no dual channel. The only thing borrowed from the older, more elaborate
 * esp32-eeg-ap-dashboard-v2.1 sketch is the AP itself: WiFi.softAP(),
 * captive-portal DNS, and the WebServer + WebSocketsServer combo that keeps
 * loop() from ever blocking (a blocking /stream handler is what froze v1).
 *
 * ── Protocol (plain-text WebSocket frames, one per sample) ─────────────
 *   ESP32 -> Browser:
 *     D<adc>,<t_ms>          live sample, sent always
 *     L<t_ms>,<adc>          CSV line, sent only while logging
 *     S:LOG_STARTED:<file>:<durationS>
 *     S:LOG_COMPLETE:<file>:<sampleCount>
 *     S:LOG_STOPPED:<file>:<sampleCount>
 *     S:LOG_ERROR:<reason>
 *   Browser -> ESP32:
 *     C:START:<durationSeconds>
 *     C:STOP
 *
 * Library: "WebSockets" by Markus Sattler (Arduino Library Manager).
 * Everything else is core WiFi/DNSServer/WebServer.
 * No filesystem used -- any partition scheme works.
 */

#include <WiFi.h>
#include <DNSServer.h>
#include <WebServer.h>
#include <WebSocketsServer.h>

// ============================================================
// USER SETTINGS
// ============================================================
#define AP_SSID              "EXG-Monitor"
#define AP_PASS              "exg123456"      // WPA2, 8+ chars
#define SENSOR_NAME          "EXG-Sensor"      // used in the downloaded filename

#define ADC_PIN              3                // single, generic 12-bit ADC input
#define STATUS_LED           2                 // onboard LED, on while logging

#define SAMPLE_RATE_HZ       250
#define MAX_LOG_DURATION_S   28800             // 8-hour safety cap
// ============================================================

#define SAMPLE_INTERVAL_US  (1000000UL / SAMPLE_RATE_HZ)
#define WS_PORT              81
#define HTTP_PORT            80
#define DNS_PORT             53

WebServer        server(HTTP_PORT);
WebSocketsServer webSocket(WS_PORT);
DNSServer        dnsServer;

uint32_t lastSampleUs = 0;

bool     isLogging      = false;
bool     stopRequested  = false;
uint32_t logStartMs     = 0;
uint32_t logDurationMs  = 0;
uint32_t logSampleNo    = 0;
char     logFilename[64];


// ============================================================
// DASHBOARD HTML -- self-contained, works fully offline.
// __SENSOR_NAME__ / __ADC_PIN__ are substituted at request time.
// ============================================================
static const char* DASHBOARD_HTML = R"HTMLPAGE(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EXG Monitor</title>
<style>
:root{
  --bg:#f6f6f4; --surface:#ffffff; --border:#dcdcd7;
  --text:#1b1b19; --muted:#6c6c66; --accent:#2f6f4f; --accent-text:#ffffff;
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#131311; --surface:#1b1b19; --border:#333330;
    --text:#e8e6e0; --muted:#98988f; --accent:#5fae82; --accent-text:#0d1a12;
  }
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     background:var(--bg);color:var(--text);padding:2rem 1.25rem}
.wrap{max-width:720px;margin:0 auto}
h1{font-size:1.05rem;font-weight:600;letter-spacing:.01em}
.meta{font-size:.78rem;color:var(--muted);margin-top:.25rem}
.status{display:flex;align-items:center;gap:.45rem;font-size:.78rem;
        color:var(--muted);margin-top:.7rem}
.status .dot{width:6px;height:6px;border-radius:50%;background:var(--muted)}
.status .dot.on{background:var(--accent)}
.panel{background:var(--surface);border:1px solid var(--border);
       border-radius:6px;padding:1.25rem;margin-top:1rem}
.readout{display:flex;align-items:baseline;gap:.6rem}
.readout .value{font:600 2.3rem/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
                 font-variant-numeric:tabular-nums}
.readout .unit{font-size:.82rem;color:var(--muted)}
.subreadouts{display:flex;gap:1.5rem;margin-top:.85rem;font-size:.78rem;color:var(--muted)}
.subreadouts b{color:var(--text);font-variant-numeric:tabular-nums;font-weight:600}
canvas{width:100%;height:200px;display:block;border-radius:4px}
.controls{display:flex;gap:.75rem;flex-wrap:wrap;align-items:flex-end}
.field{display:flex;flex-direction:column;gap:.3rem}
label{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
input,select{padding:.5rem .6rem;background:var(--bg);border:1px solid var(--border);
             border-radius:4px;color:var(--text);font-size:.85rem}
input[type=number]{width:100px}
button{padding:.55rem 1rem;border:1px solid transparent;border-radius:4px;
       font-size:.85rem;font-weight:600;cursor:pointer}
button.primary{background:var(--accent);color:var(--accent-text)}
button.secondary{background:transparent;border-color:var(--border);color:var(--text)}
button:disabled{opacity:.4;cursor:not-allowed}
.logline{font-size:.8rem;color:var(--muted);margin-top:.9rem}
.logline b{color:var(--text)}
.track{height:4px;background:var(--bg);border:1px solid var(--border);
       border-radius:99px;margin-top:.5rem;overflow:hidden}
.fill{height:100%;background:var(--accent);width:0%}
.footnote{font-size:.72rem;color:var(--muted);margin-top:.8rem;line-height:1.5}
.panel-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:.6rem}
.panel-title{font-size:.78rem;font-weight:600}
.panel-sub{font-size:.75rem;color:var(--muted)}
.panel-sub b{color:var(--text);font-variant-numeric:tabular-nums;font-weight:600}
.caption{font-size:.72rem;color:var(--muted);margin-top:.5rem;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>EXG Monitor</h1>
    <div class="meta" id="sensorLabel">Sensor: __SENSOR_NAME__ (GPIO__ADC_PIN__)</div>
    <div class="status">
      <span class="dot" id="connDot"></span>
      <span id="connText">Connecting</span>
      <span style="margin-left:auto" id="rateText"></span>
    </div>
  </header>

  <div class="panel">
    <div class="readout">
      <span class="value" id="bigVal">--</span><span class="unit">raw / 4095</span>
    </div>
    <div class="subreadouts">
      <div>Voltage <b id="voltVal">-- V</b></div>
      <div>Samples <b id="totalSamples">0</b></div>
    </div>
  </div>

  <div class="panel">
    <canvas id="graph"></canvas>
  </div>

  <div class="panel">
    <div class="panel-head">
      <span class="panel-title">Frequency spectrum</span>
      <span class="panel-sub">Peak <b id="peakFreq">-- Hz</b></span>
    </div>
    <canvas id="fftCanvas"></canvas>
    <div class="caption" id="fftCaption">Collecting samples…</div>
  </div>

  <div class="panel">
    <div class="panel-head">
      <span class="panel-title">Spectrogram</span>
      <span class="panel-sub">0-45 Hz, 10 s history</span>
    </div>
    <canvas id="specCanvas"></canvas>
  </div>

  <div class="panel">
    <div class="controls">
      <div class="field">
        <label>Duration</label>
        <input id="durVal" type="number" min="1" max="28800" value="60">
      </div>
      <div class="field">
        <label>Unit</label>
        <select id="durUnit">
          <option value="1">Seconds</option>
          <option value="60" selected>Minutes</option>
          <option value="3600">Hours</option>
        </select>
      </div>
      <button class="primary" id="startBtn">Start logging</button>
      <button class="secondary" id="stopBtn" disabled>Stop</button>
    </div>
    <div class="logline" id="logStatus">Not logging.</div>
    <div class="track"><div class="fill" id="progressFill"></div></div>
    <div class="footnote" id="memLabel">
      CSV is built in a background thread and downloads automatically to
      this device when the session ends. Nothing is stored on the board.
    </div>
  </div>
</div>

<script>
// ── Worker: parses every WS frame, owns the sample/CSV buffers ─────────
const workerSrc = `
  const MAX_POINTS = 750;
  let totalSamples = 0, rateCount = 0;
  let csvLines = [], csvBytes = 0, currentFilename = '';

  setInterval(() => {
    postMessage({ type: 'rate', hz: rateCount });
    rateCount = 0;
  }, 1000);

  // ── Spectral analysis ──────────────────────────────────────────────
  // Causal (not zero-phase) filtering, deliberately: this is a live view,
  // so it only needs the settled steady-state response, the same way a
  // real embedded filter (biquad, running continuously) behaves -- not
  // the offline analyzer's block filtfilt over a whole recording.
  const FS = 250;
  const FFT_WINDOW = 1024;       // ~4.1 s -- main spectrum resolution
  const SPEC_NPERSEG = 512;      // ~2.0 s -- spectrogram column resolution
  const MAX_DISPLAY_HZ = 45;
  const ANALYSIS_INTERVAL_MS = 150;

  // Fixed-fs Butterworth SOS cascades (scipy.signal.butter, fs=250 Hz):
  // 4th-order 48-52 Hz bandstop (mains notch), 6th-order 2-45 Hz bandpass.
  const NOTCH_SOS = [
    { b0:0.8768538897, b1:-0.5426108480, b2:0.8768538897, a1:-0.5559418416, a2:0.9106714017 },
    { b0:1.0000000000, b1:-0.6188155797, b2:1.0000000000, a1:-0.6263209047, a2:0.9117355253 },
    { b0:1.0000000000, b1:-0.6188155797, b2:1.0000000000, a1:-0.5190315099, a2:0.9617446105 },
    { b0:1.0000000000, b1:-0.6188155797, b2:1.0000000000, a1:-0.6927031558, a2:0.9628621807 },
  ];
  const BANDPASS_SOS = [
    { b0:0.0050169038, b1:0.0100338077, b2:0.0050169038, a1:-0.5314438085, a2:0.0885613944 },
    { b0:1.0000000000, b1:2.0000000000, b2:1.0000000000, a1:-0.5695041150, a2:0.2485648698 },
    { b0:1.0000000000, b1:2.0000000000, b2:1.0000000000, a1:-0.7059870674, a2:0.6436094670 },
    { b0:1.0000000000, b1:-2.0000000000, b2:1.0000000000, a1:-1.8980410339, a2:0.9008523898 },
    { b0:1.0000000000, b1:-2.0000000000, b2:1.0000000000, a1:-1.9292086647, a2:0.9318395149 },
    { b0:1.0000000000, b1:-2.0000000000, b2:1.0000000000, a1:-1.9735317682, a2:0.9760506377 },
  ];
  const notchState = NOTCH_SOS.map(() => ({ z1: 0, z2: 0 }));
  const bpState = BANDPASS_SOS.map(() => ({ z1: 0, z2: 0 }));

  function biquadStep(sections, state, x) {
    let y = x;
    for (let i = 0; i < sections.length; i++) {
      const s = sections[i], st = state[i];
      const w = y - s.a1 * st.z1 - s.a2 * st.z2;
      y = s.b0 * w + s.b1 * st.z1 + s.b2 * st.z2;
      st.z2 = st.z1;
      st.z1 = w;
    }
    return y;
  }

  function applyFilters(volts) {
    return biquadStep(BANDPASS_SOS, bpState, biquadStep(NOTCH_SOS, notchState, volts));
  }

  const filteredBuf = [];

  function hannWindow(n) {
    const w = new Float64Array(n);
    for (let i = 0; i < n; i++) w[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1));
    return w;
  }
  const HANN_FFT = hannWindow(FFT_WINDOW);
  const HANN_SPEC = hannWindow(SPEC_NPERSEG);

  // In-place iterative radix-2 FFT (Cooley-Tukey, decimation in time).
  function fft(re, im) {
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) {
        let t = re[i]; re[i] = re[j]; re[j] = t;
        t = im[i]; im[i] = im[j]; im[j] = t;
      }
    }
    for (let len = 2; len <= n; len <<= 1) {
      const half = len >> 1;
      const ang = -2 * Math.PI / len;
      const wr0 = Math.cos(ang), wi0 = Math.sin(ang);
      for (let i = 0; i < n; i += len) {
        let cwr = 1, cwi = 0;
        for (let k = 0; k < half; k++) {
          const ur = re[i + k], ui = im[i + k];
          const tr = re[i + k + half] * cwr - im[i + k + half] * cwi;
          const ti = re[i + k + half] * cwi + im[i + k + half] * cwr;
          re[i + k] = ur + tr; im[i + k] = ui + ti;
          re[i + k + half] = ur - tr; im[i + k + half] = ui - ti;
          const nwr = cwr * wr0 - cwi * wi0;
          const nwi = cwr * wi0 + cwi * wr0;
          cwr = nwr; cwi = nwi;
        }
      }
    }
  }

  function magnitudeSpectrum(samples, n, window) {
    const re = new Float64Array(n), im = new Float64Array(n);
    for (let i = 0; i < n; i++) re[i] = samples[i] * window[i];
    fft(re, im);
    const bins = n / 2 + 1;
    const mag = new Array(bins);
    for (let k = 0; k < bins; k++) mag[k] = Math.sqrt(re[k] * re[k] + im[k] * im[k]) / n;
    return mag;
  }

  // scipy-style PSD ('density' scaling): |X|^2 / (fs * sum(window^2)),
  // doubled for the single-sided spectrum (all bins except DC/Nyquist).
  function psdSpectrum(samples, n, window) {
    const re = new Float64Array(n), im = new Float64Array(n);
    let winPow = 0;
    for (let i = 0; i < n; i++) { re[i] = samples[i] * window[i]; winPow += window[i] * window[i]; }
    fft(re, im);
    const scale = 1 / (FS * winPow);
    const bins = n / 2 + 1;
    const psd = new Array(bins);
    for (let k = 0; k < bins; k++) {
      let p = (re[k] * re[k] + im[k] * im[k]) * scale;
      if (k > 0 && k < n / 2) p *= 2;
      psd[k] = p;
    }
    return psd;
  }

  function binsUpTo(n, hz) {
    const df = FS / n;
    return Math.min(n / 2 + 1, Math.floor(hz / df) + 1);
  }
  const FFT_BINS = binsUpTo(FFT_WINDOW, MAX_DISPLAY_HZ);
  const SPEC_BINS = binsUpTo(SPEC_NPERSEG, MAX_DISPLAY_HZ);

  setInterval(() => {
    if (filteredBuf.length < FFT_WINDOW) {
      postMessage({ type: 'analysisWaiting', have: filteredBuf.length, need: FFT_WINDOW });
      return;
    }

    const full = filteredBuf.slice(-FFT_WINDOW);
    const fftMag = magnitudeSpectrum(full, FFT_WINDOW, HANN_FFT).slice(0, FFT_BINS);

    let peakIdx = 1, peakVal = -1;
    for (let k = 1; k < fftMag.length; k++) if (fftMag[k] > peakVal) { peakVal = fftMag[k]; peakIdx = k; }

    const segment = full.slice(FFT_WINDOW - SPEC_NPERSEG);
    const specCol = psdSpectrum(segment, SPEC_NPERSEG, HANN_SPEC).slice(0, SPEC_BINS);

    postMessage({
      type: 'analysis',
      fftMag, fftDf: FS / FFT_WINDOW,
      peakHz: peakIdx * (FS / FFT_WINDOW),
      specCol, specDf: FS / SPEC_NPERSEG
    });
  }, ANALYSIS_INTERVAL_MS);

  self.onmessage = (e) => {
    const data = e.data;
    if (!data || !data.length) return;
    const prefix = data[0];

    if (prefix === 'D') {
      const rest = data.slice(1);
      const comma = rest.indexOf(',');
      if (comma === -1) return;
      const v = parseInt(rest.slice(0, comma), 10);
      const t = parseInt(rest.slice(comma + 1), 10);
      totalSamples++; rateCount++;

      const volts = (v / 4095) * 3.3;
      filteredBuf.push(applyFilters(volts));
      if (filteredBuf.length > FFT_WINDOW) filteredBuf.shift();

      postMessage({ type: 'graph', v, t, total: totalSamples });

    } else if (prefix === 'L') {
      const rest = data.slice(1);
      const comma = rest.indexOf(',');
      if (comma === -1) return;
      const line = rest.slice(0, comma) + ',' + rest.slice(comma + 1) + '\\n';
      csvLines.push(line);
      csvBytes += line.length;
      if ((csvLines.length % 25) === 0) postMessage({ type: 'buffer', bytes: csvBytes });

    } else if (prefix === 'S') {
      const parts = data.slice(2).split(':');
      const kind = parts[0];

      if (kind === 'LOG_STARTED') {
        currentFilename = parts[1];
        const durationS = parseInt(parts[2], 10);
        csvLines = ['timestamp_ms,adc\\n'];
        csvBytes = csvLines[0].length;
        totalSamples = 0;
        postMessage({ type: 'logStarted', filename: currentFilename, durationS });

      } else if (kind === 'LOG_COMPLETE' || kind === 'LOG_STOPPED') {
        const filename = parts[1];
        const count = parseInt(parts[2], 10);
        const blob = new Blob(csvLines, { type: 'text/csv' });
        postMessage({
          type: kind === 'LOG_COMPLETE' ? 'logComplete' : 'logStopped',
          filename, count, blob
        });
        csvLines = []; csvBytes = 0;

      } else if (kind === 'LOG_ERROR') {
        postMessage({ type: 'logError', reason: parts.slice(1).join(':') });
      }
    }
  };
`;

const workerUrl = URL.createObjectURL(new Blob([workerSrc], { type: 'application/javascript' }));
const worker = new Worker(workerUrl);

// ── DOM refs ─────────────────────────────────────────────────────────
const connDot = document.getElementById('connDot');
const connText = document.getElementById('connText');
const rateText = document.getElementById('rateText');
const bigVal = document.getElementById('bigVal');
const voltVal = document.getElementById('voltVal');
const totalSamplesEl = document.getElementById('totalSamples');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const durVal = document.getElementById('durVal');
const durUnit = document.getElementById('durUnit');
const logStatus = document.getElementById('logStatus');
const progressFill = document.getElementById('progressFill');
const memLabel = document.getElementById('memLabel');
const peakFreqEl = document.getElementById('peakFreq');
const fftCaption = document.getElementById('fftCaption');

// ── Live graph state (mirrors what the worker is tracking) ─────────────
const MAX_POINTS = 750;
let drawBuf = [];
let logDurationMs = 0, logEndsAt = 0, progressTimer = null;

worker.onmessage = (e) => {
  const msg = e.data;
  switch (msg.type) {
    case 'graph':
      drawBuf.push({ v: msg.v, t: msg.t });
      if (drawBuf.length > MAX_POINTS) drawBuf.shift();
      bigVal.textContent = msg.v;
      voltVal.textContent = (msg.v * 3.3 / 4095).toFixed(3) + ' V';
      totalSamplesEl.textContent = msg.total.toLocaleString();
      break;

    case 'rate':
      rateText.textContent = msg.hz + ' Hz';
      break;

    case 'buffer':
      setMemLabel(msg.bytes);
      break;

    case 'analysisWaiting':
      fftCaption.textContent = 'Collecting samples… ' + Math.round(100 * msg.have / msg.need) + '%';
      break;

    case 'analysis':
      fftCaption.textContent = '';
      drawFFT(msg.fftMag, msg.fftDf, msg.peakHz);
      pushSpecColumn(msg.specCol, msg.specDf);
      break;

    case 'logStarted':
      logDurationMs = msg.durationS * 1000;
      logEndsAt = Date.now() + logDurationMs;
      startBtn.disabled = true;
      stopBtn.disabled = false;
      logStatus.innerHTML = 'Logging to <b>' + msg.filename + '</b>…';
      if (progressTimer) clearInterval(progressTimer);
      progressTimer = setInterval(tickProgress, 250);
      break;

    case 'logComplete':
    case 'logStopped': {
      if (progressTimer) clearInterval(progressTimer);
      const manual = msg.type === 'logStopped';
      progressFill.style.width = manual ? progressFill.style.width : '100%';
      startBtn.disabled = false;
      stopBtn.disabled = true;
      logStatus.innerHTML = (manual ? 'Stopped: ' : 'Complete: ') +
        '<b>' + msg.filename + '</b> — ' + msg.count.toLocaleString() + ' samples.';
      triggerDownload(msg.blob, msg.filename);
      setTimeout(() => { progressFill.style.width = '0%'; setMemLabel(0); }, 4000);
      break;
    }

    case 'logError':
      if (progressTimer) clearInterval(progressTimer);
      startBtn.disabled = false;
      stopBtn.disabled = true;
      logStatus.textContent = 'Error: ' + msg.reason;
      break;
  }
};

function setMemLabel(bytes) {
  const kb = (bytes / 1024).toFixed(0);
  memLabel.textContent = bytes > 0
    ? 'Buffer: ' + kb + ' KB — downloads automatically when the session ends.'
    : 'CSV is built in a background thread and downloads automatically to this device when the session ends. Nothing is stored on the board.';
}

function tickProgress() {
  const rem = Math.max(0, logEndsAt - Date.now());
  const pct = Math.min(100, 100 * (1 - rem / logDurationMs));
  progressFill.style.width = pct + '%';
  logStatus.innerHTML = 'Logging… ' + Math.ceil(rem / 1000) + 's remaining';
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 15000);
}

// ── WebSocket: async connect/reconnect loop, no parsing here ───────────
let ws, connected = false;

function setDot(on) {
  connDot.classList.toggle('on', on);
  connText.textContent = on ? 'Connected' : 'Disconnected — retrying…';
}

async function connectLoop() {
  for (;;) {
    await new Promise((resolve) => {
      ws = new WebSocket('ws://' + location.hostname + ':81/');
      ws.onopen = () => { connected = true; setDot(true); };
      ws.onmessage = (ev) => worker.postMessage(ev.data);
      ws.onerror = () => ws.close();
      ws.onclose = () => { connected = false; setDot(false); resolve(); };
    });
    await new Promise((r) => setTimeout(r, 1500));
  }
}
connectLoop();

startBtn.addEventListener('click', () => {
  if (!connected) { alert('Not connected.'); return; }
  const val = parseInt(durVal.value, 10);
  const unit = parseInt(durUnit.value, 10);
  if (!val || val <= 0) { alert('Enter a valid duration.'); return; }
  ws.send('C:START:' + (val * unit));
});

stopBtn.addEventListener('click', () => {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send('C:STOP');
});

// ── Canvas: plain-line trace, colors read from the active theme ────────
const canvas = document.getElementById('graph');
const ctx = canvas.getContext('2d');

const fftCanvas = document.getElementById('fftCanvas');
const fftCtx = fftCanvas.getContext('2d');
const specCanvas = document.getElementById('specCanvas');
const specCtx = specCanvas.getContext('2d');

function resizeCanvas() {
  canvas.width = canvas.clientWidth * devicePixelRatio;
  canvas.height = canvas.clientHeight * devicePixelRatio;
  fftCanvas.width = fftCanvas.clientWidth * devicePixelRatio;
  fftCanvas.height = fftCanvas.clientHeight * devicePixelRatio;
  specCanvas.width = specCanvas.clientWidth * devicePixelRatio;
  specCanvas.height = specCanvas.clientHeight * devicePixelRatio;
}
window.addEventListener('resize', resizeCanvas);
resizeCanvas();

function themeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function draw() {
  requestAnimationFrame(draw);
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  if (drawBuf.length < 2) return;

  let mn = Infinity, mx = -Infinity;
  for (const s of drawBuf) { if (s.v < mn) mn = s.v; if (s.v > mx) mx = s.v; }
  if (mn === mx) { mn -= 20; mx += 20; }
  const pad = (mx - mn) * 0.08;
  mn -= pad; mx += pad;

  ctx.strokeStyle = themeColor('--border');
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const y = (h / 4) * i;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }

  // Value axis (left) and time axis (right), read off the actual buffered
  // span -- not a fixed assumption -- so labels stay correct even before
  // the buffer is full or if the sample rate ever changes.
  ctx.fillStyle = themeColor('--muted');
  ctx.font = (9 * devicePixelRatio) + 'px sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(Math.round(mx).toString(), 4 * devicePixelRatio, 11 * devicePixelRatio);
  ctx.fillText(Math.round(mn).toString(), 4 * devicePixelRatio, h - 4 * devicePixelRatio);
  ctx.textAlign = 'right';
  const spanS = ((drawBuf[drawBuf.length - 1].t - drawBuf[0].t) / 1000).toFixed(1);
  ctx.fillText('now', w - 4 * devicePixelRatio, 11 * devicePixelRatio);
  ctx.fillText('-' + spanS + 's', w - 4 * devicePixelRatio, h - 4 * devicePixelRatio);

  ctx.strokeStyle = themeColor('--accent');
  ctx.lineWidth = 1.6 * devicePixelRatio;
  ctx.lineJoin = 'round';
  ctx.beginPath();
  // Index against the buffer's own length, not the fixed capacity -- so the
  // trace fills the full canvas width immediately instead of starting
  // squeezed into the left edge while the buffer is still warming up.
  const lastIdx = drawBuf.length - 1;
  for (let i = 0; i < drawBuf.length; i++) {
    const x = (i / lastIdx) * w;
    const y = h - ((drawBuf[i].v - mn) / (mx - mn)) * h;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
}
draw();

// ── Frequency spectrum: line chart with EEG-band boundary guides ───────
const BAND_BOUNDS = [0.5, 4, 8, 13, 30, 45];
const BAND_LABELS = ['Delta', 'Theta', 'Alpha', 'Beta', 'Gamma'];

function drawFFT(mag, df, peakHz) {
  const w = fftCanvas.width, h = fftCanvas.height;
  fftCtx.clearRect(0, 0, w, h);
  if (!mag.length) return;

  let mx = 1e-9;
  for (const m of mag) if (m > mx) mx = m;
  const maxHz = (mag.length - 1) * df;

  fftCtx.strokeStyle = themeColor('--border');
  fftCtx.fillStyle = themeColor('--muted');
  fftCtx.font = (9 * devicePixelRatio) + 'px sans-serif';
  fftCtx.lineWidth = 1;
  fftCtx.textAlign = 'left';
  for (let i = 0; i < BAND_BOUNDS.length; i++) {
    const x = (BAND_BOUNDS[i] / maxHz) * w;
    fftCtx.beginPath(); fftCtx.moveTo(x, 0); fftCtx.lineTo(x, h); fftCtx.stroke();
    if (BAND_LABELS[i]) fftCtx.fillText(BAND_LABELS[i], x + 3 * devicePixelRatio, 11 * devicePixelRatio);
  }

  // Hz axis (bottom) and a magnitude scale reference (top-right), so the
  // chart reads as an actual spectrum rather than an unlabeled squiggle.
  for (const hz of [0, 10, 20, 30, 40]) {
    if (hz > maxHz) continue;
    const x = (hz / maxHz) * w;
    fftCtx.fillText(hz + 'Hz', x + 2 * devicePixelRatio, h - 3 * devicePixelRatio);
  }
  fftCtx.textAlign = 'right';
  fftCtx.fillText('max ' + mx.toExponential(1) + ' V', w - 4 * devicePixelRatio, 11 * devicePixelRatio);

  fftCtx.strokeStyle = themeColor('--accent');
  fftCtx.lineWidth = 1.4 * devicePixelRatio;
  fftCtx.lineJoin = 'round';
  fftCtx.beginPath();
  for (let k = 0; k < mag.length; k++) {
    const x = (k / (mag.length - 1)) * w;
    const y = h - (mag[k] / (mx * 1.15)) * h;
    k === 0 ? fftCtx.moveTo(x, y) : fftCtx.lineTo(x, y);
  }
  fftCtx.stroke();

  peakFreqEl.textContent = peakHz.toFixed(1) + ' Hz';
}

// ── Spectrogram: scrolling waterfall, rebuilt from a small value matrix ─
// (rebuilding the whole offscreen image each tick is trivial at this size
// and avoids drawImage-onto-itself aliasing hazards).
const SPEC_HISTORY_COLS = 67; // ~10 s at the worker's 150 ms analysis tick
const ANALYSIS_INTERVAL_MS = 150; // must match the worker's ANALYSIS_INTERVAL_MS
const SPEC_HISTORY_S = ((SPEC_HISTORY_COLS * ANALYSIS_INTERVAL_MS) / 1000).toFixed(0);
let specMatrix = null, specRows = 0;
let specHistoryCanvas = null, specHistoryCtx = null;
let specRunMax = 1e-9;

// Text chip with its own dark backing, since the heatmap underneath it can
// be anywhere from dark purple to bright yellow -- plain themed text alone
// wouldn't stay legible against it.
function labelChip(c, text, x, y, align) {
  c.font = (9 * devicePixelRatio) + 'px sans-serif';
  c.textAlign = align;
  const pad = 3 * devicePixelRatio;
  const bw = c.measureText(text).width + pad * 2;
  const bh = 13 * devicePixelRatio;
  const bx = align === 'right' ? x - bw + pad : x - pad;
  c.fillStyle = 'rgba(0,0,0,0.55)';
  c.fillRect(bx, y - bh + 4 * devicePixelRatio, bw, bh);
  c.fillStyle = '#f4f4f2';
  c.fillText(text, x, y);
}

function viridisApprox(t) {
  const stops = [
    [0.00, 68, 1, 84], [0.25, 59, 82, 139], [0.50, 33, 145, 140],
    [0.75, 94, 201, 98], [1.00, 253, 231, 37]
  ];
  t = Math.max(0, Math.min(1, t));
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, r0, g0, b0] = stops[i], [t1, r1, g1, b1] = stops[i + 1];
    if (t >= t0 && t <= t1) {
      const f = (t - t0) / (t1 - t0);
      return [Math.round(r0 + f * (r1 - r0)), Math.round(g0 + f * (g1 - g0)), Math.round(b0 + f * (b1 - b0))];
    }
  }
  const last = stops[stops.length - 1];
  return [last[1], last[2], last[3]];
}

function pushSpecColumn(specCol, specDf) {
  if (!specMatrix || specRows !== specCol.length) {
    specRows = specCol.length;
    specMatrix = new Float64Array(specRows * SPEC_HISTORY_COLS);
    specHistoryCanvas = document.createElement('canvas');
    specHistoryCanvas.width = SPEC_HISTORY_COLS;
    specHistoryCanvas.height = specRows;
    specHistoryCtx = specHistoryCanvas.getContext('2d');
  }

  for (let r = 0; r < specRows; r++) {
    const base = r * SPEC_HISTORY_COLS;
    for (let c = 0; c < SPEC_HISTORY_COLS - 1; c++) specMatrix[base + c] = specMatrix[base + c + 1];
    specMatrix[base + SPEC_HISTORY_COLS - 1] = specCol[r];
  }

  let colMax = 0;
  for (const p of specCol) if (p > colMax) colMax = p;
  specRunMax = Math.max(colMax, specRunMax * 0.995, 1e-12);

  const img = specHistoryCtx.createImageData(SPEC_HISTORY_COLS, specRows);
  for (let r = 0; r < specRows; r++) {
    const bin = specRows - 1 - r; // low frequency at the bottom
    for (let c = 0; c < SPEC_HISTORY_COLS; c++) {
      const val = specMatrix[bin * SPEC_HISTORY_COLS + c];
      const norm = Math.max(0, (val / specRunMax - 0.001) / (1 - 0.001));
      const [rr, gg, bb] = viridisApprox(norm);
      const o = (r * SPEC_HISTORY_COLS + c) * 4;
      img.data[o] = rr; img.data[o + 1] = gg; img.data[o + 2] = bb; img.data[o + 3] = 255;
    }
  }
  specHistoryCtx.putImageData(img, 0, 0);

  const w = specCanvas.width, h = specCanvas.height;
  specCtx.imageSmoothingEnabled = true;
  specCtx.clearRect(0, 0, w, h);
  specCtx.drawImage(specHistoryCanvas, 0, 0, w, h);

  const topHz = Math.round((specRows - 1) * specDf);
  labelChip(specCtx, topHz + 'Hz', 4 * devicePixelRatio, 13 * devicePixelRatio, 'left');
  labelChip(specCtx, '0Hz', 4 * devicePixelRatio, h - 4 * devicePixelRatio, 'left');
  labelChip(specCtx, 'now', w - 4 * devicePixelRatio, 13 * devicePixelRatio, 'right');
  labelChip(specCtx, '-' + SPEC_HISTORY_S + 's', w - 4 * devicePixelRatio, h - 4 * devicePixelRatio, 'right');
}
</script>
</body>
</html>
)HTMLPAGE";


// ============================================================
// HTTP handlers
// ============================================================
void handleRoot() {
  String html = DASHBOARD_HTML;
  html.replace("__SENSOR_NAME__", SENSOR_NAME);
  html.replace("__ADC_PIN__", String(ADC_PIN));
  server.send(200, "text/html", html);
}

// Redirects every captive-portal probe URL to the dashboard, which is what
// triggers the "Sign in to network" popup on phones/laptops.
void handleCaptive() {
  server.sendHeader("Location", "http://192.168.4.1/", true);
  server.send(302, "text/plain", "");
}


// ============================================================
// WebSocket control-frame handler
// ============================================================
void webSocketEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
  if (type != WStype_TEXT || length == 0) return;
  String msg = String((char*)payload).substring(0, length);

  if (msg.startsWith("C:START:") && !isLogging) {
    uint32_t durationSec = (uint32_t)msg.substring(8).toInt();

    if (durationSec == 0 || durationSec > MAX_LOG_DURATION_S) {
      webSocket.sendTXT(num,
        "S:LOG_ERROR:Duration out of range (1-" + String(MAX_LOG_DURATION_S) + "s)");
      return;
    }

    snprintf(logFilename, sizeof(logFilename), "%s_%lu_%lus.csv",
             SENSOR_NAME, (unsigned long)millis(), (unsigned long)durationSec);

    logSampleNo   = 0;
    logDurationMs = durationSec * 1000UL;
    logStartMs    = millis();
    stopRequested = false;
    isLogging     = true;
    digitalWrite(STATUS_LED, HIGH);

    char wsMsg[96];
    snprintf(wsMsg, sizeof(wsMsg), "S:LOG_STARTED:%s:%lu",
             logFilename, (unsigned long)durationSec);
    webSocket.broadcastTXT(wsMsg);

  } else if (msg == "C:STOP" && isLogging) {
    stopRequested = true;
  }
}

void finishLogging(bool timerExpired) {
  isLogging = false;
  digitalWrite(STATUS_LED, LOW);

  char wsMsg[96];
  snprintf(wsMsg, sizeof(wsMsg), "S:%s:%s:%lu",
           timerExpired ? "LOG_COMPLETE" : "LOG_STOPPED",
           logFilename, (unsigned long)logSampleNo);
  webSocket.broadcastTXT(wsMsg);
}


// ============================================================
// SETUP
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(300);

  pinMode(STATUS_LED, OUTPUT);
  digitalWrite(STATUS_LED, LOW);

  analogReadResolution(12);
  pinMode(ADC_PIN, INPUT);
#if defined(ESP32)
  analogSetPinAttenuation(ADC_PIN, ADC_11db);
#endif

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  IPAddress apIP = WiFi.softAPIP();
  Serial.printf("[AP] SSID: \"%s\"  ->  http://%s\n", AP_SSID, apIP.toString().c_str());

  // Wildcard DNS: every domain resolves here, which is what triggers the
  // captive-portal popup on phones/laptops the moment they join the AP.
  dnsServer.start(DNS_PORT, "*", apIP);

  server.on("/",                    HTTP_GET, handleRoot);
  server.on("/generate_204",        HTTP_GET, handleCaptive);  // Android
  server.on("/hotspot-detect.html", HTTP_GET, handleCaptive);  // Apple
  server.on("/ncsi.txt",            HTTP_GET, handleCaptive);  // Windows
  server.on("/connecttest.txt",     HTTP_GET, handleCaptive);  // Windows 10
  server.on("/redirect",            HTTP_GET, handleCaptive);
  server.onNotFound(handleCaptive);
  server.begin();

  webSocket.begin();
  webSocket.onEvent(webSocketEvent);

  lastSampleUs = micros();

  Serial.printf("[Setup] Sampling GPIO%d at %d Hz. Connect to \"%s\" and open http://%s\n",
                ADC_PIN, SAMPLE_RATE_HZ, AP_SSID, apIP.toString().c_str());
}


// ============================================================
// LOOP -- never blocks
// ============================================================
void loop() {
  dnsServer.processNextRequest();
  server.handleClient();
  webSocket.loop();

  uint32_t nowUs = micros();
  if (nowUs - lastSampleUs >= SAMPLE_INTERVAL_US) {
    lastSampleUs = nowUs;

    uint16_t raw = analogRead(ADC_PIN);
    uint32_t nowMs = millis();

    char msg[32];
    int len = snprintf(msg, sizeof(msg), "D%u,%lu", raw, (unsigned long)nowMs);
    webSocket.broadcastTXT(msg, len);

    if (isLogging) {
      logSampleNo++;
      len = snprintf(msg, sizeof(msg), "L%lu,%u", (unsigned long)nowMs, raw);
      webSocket.broadcastTXT(msg, len);
    }
  }

  if (isLogging) {
    bool timerDone = (millis() - logStartMs) >= logDurationMs;
    if (timerDone || stopRequested) {
      finishLogging(timerDone && !stopRequested);
    }
  }
}
