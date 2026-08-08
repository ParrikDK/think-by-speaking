// Shared mic-capture helpers (arch review candidate 6, 2026-08-06).
// The manual push-to-talk flow (ChatScreen) and the VAD flow
// (useSileroVAD) each owned a copy of the RMS volume loop and the
// MediaRecorder + suppress-send protocol — the F8 "trailing blob" bug had
// to be fixed twice because of it. One implementation now.

/** RMS analyser over a mic stream: returns { analyser, stop }.
 *  Scale-up factor 2.5 matches mic sensitivity (clamped to 0..1). */
export function createRmsAnalyser(ctx, stream) {
  const sourceNode = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.8;
  sourceNode.connect(analyser);
  return {
    analyser,
    stop() {
      try { sourceNode.disconnect(); } catch { /* already disconnected */ }
    },
  };
}

/** rAF volume loop → onLevel(0..1), throttled to ~12Hz. Returns cancel(). */
export function startVolumeLoop(analyser, onLevel) {
  const dataArray = new Uint8Array(analyser.frequencyBinCount);
  let raf = 0;
  let lastUpdate = performance.now();
  const tick = (now) => {
    analyser.getByteTimeDomainData(dataArray);
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const val = dataArray[i] / 128 - 1;
      sum += val * val;
    }
    const rms = Math.sqrt(sum / dataArray.length);
    if (now - lastUpdate > 80) {
      onLevel(Math.min(1, rms * 2.5));
      lastUpdate = now;
    }
    raf = requestAnimationFrame(tick);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}

/**
 * One recording session: MediaRecorder over *stream* with data collection.
 * onBlob(blob) fires exactly once when the recorder stops — unless
 * suppressSend is true at stop time (cleanup-initiated stops must never
 * send a trailing blob; audit F8). Returns the recorder (call stop() to
 * end the session).
 */
export function startRecorder(stream, mimeType, { onBlob, suppressSendRef }) {
  const chunks = [];
  const mr = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  mr.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
  mr.onstop = () => {
    const blob = new Blob(chunks, { type: mr.mimeType || 'audio/webm' });
    if (blob.size > 0 && !suppressSendRef.current) onBlob(blob);
  };
  mr.start();
  return mr;
}
