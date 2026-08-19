// Audio delivery metrics — the "how you sound" pillar (v13.1).
//
// analyzeAudio(blob) decodes the recorded turn and returns:
//   { audioSecs, pitchVar } — speaking duration and the standard deviation
// of estimated pitch (F0) across frames. A low pitchVar (< ~25 Hz) means a
// monotone delivery; the server labels it from the raw value.
//
// F0 estimation is a plain normalized-autocorrelation search in the 60–400
// Hz range — no external deps, good enough to separate "monotone" from
// "varied", deliberately not a studio-grade pitch tracker.

const FRAME = 2048;   // samples per analysis frame
const HOP = 1024;     // frame advance
const MIN_F0 = 60;    // Hz
const MAX_F0 = 400;   // Hz
const ANALYZE_RATE = 16000;  // F0 is 60-400 Hz; 8 kHz Nyquist suffices

export function autocorrF0(frame, sampleRate) {
  const minLag = Math.floor(sampleRate / MAX_F0);
  const maxLag = Math.floor(sampleRate / MIN_F0);
  let bestLag = -1;
  let bestScore = 0;
  // Frame energy is lag-independent — compute once (efficiency review).
  let den = 0;
  for (let i = 0; i < frame.length; i++) den += frame[i] * frame[i];
  if (den <= 0) return null;
  for (let lag = minLag; lag <= maxLag; lag++) {
    let num = 0;
    for (let i = 0; i + lag < frame.length; i++) {
      num += frame[i] * frame[i + lag];
    }
    const score = num / den;
    if (score > bestScore) {
      bestScore = score;
      bestLag = lag;
    }
  }
  if (bestLag <= 0 || bestScore < 0.4) return null;  // voiceless/noise frame
  return sampleRate / bestLag;
}

// Pitch variance over a mono signal: decimate to 16 kHz first (~9x less
// work), scan frames, return the F0 stddev. Shared by the recorded-turn
// analysis and the realtime PTT path.
export function pitchVariance(mono, sampleRate) {
  if (!mono || mono.length < FRAME) return 0;
  const rate = sampleRate || ANALYZE_RATE;
  // Decimate to ANALYZE_RATE by stride-sampling (F0 < 400 Hz).
  let src = mono;
  if (rate > ANALYZE_RATE) {
    const stride = Math.round(rate / ANALYZE_RATE);
    const n = Math.floor(mono.length / stride);
    src = new Float32Array(n);
    for (let i = 0; i < n; i++) src[i] = mono[i * stride];
  }
  const f0s = [];
  for (let off = 0; off + FRAME < src.length; off += HOP) {
    const f0 = autocorrF0(src.subarray(off, off + FRAME), ANALYZE_RATE);
    if (f0) f0s.push(f0);
  }
  return stddev(f0s);
}

export function stddev(values) {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const v = values.reduce((a, b) => a + (b - mean) * (b - mean), 0) / (values.length - 1);
  return Math.sqrt(v);
}

export async function analyzeAudio(blob) {
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const buf = await ac.decodeAudioData(await blob.arrayBuffer());
    const mono = buf.getChannelData(0);
    const audioSecs = mono.length / buf.sampleRate;
    const pv = pitchVariance(mono, buf.sampleRate);
    await ac.close();
    return { audioSecs: Math.round(audioSecs * 10) / 10, pitchVar: Math.round(pv * 10) / 10 };
  } catch {
    // decode failure (unlikely for MediaRecorder output) — degrade to no
    // metrics rather than blocking the turn.
    return { audioSecs: 0, pitchVar: 0 };
  }
}
