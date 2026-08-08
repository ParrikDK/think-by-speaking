// src/hooks/useSileroVAD.js
// Silero VAD (MIT license, runs locally in-browser, no API keys)
// Assets are served from /public (self-hosted, no CDN):
//   /vad-bundle.min.js, /ort.wasm.bundle.min.mjs, /silero_vad_v5.onnx, /ort-wasm-*
// Hands-free behavior: speech start → record (barge-in stops tutor audio),
// 2s of trailing silence → auto-send, 10-minute hard cap per turn.
import { useState, useRef, useEffect, useCallback } from 'react';
import { pickRecorderMime, recorderBlobType } from '../utils/recorder';

const SILENCE_TIMEOUT_MS = 2000;
const MAX_RECORDING_MS = 10 * 60 * 1000;

// Load VAD dynamically (avoids Vite bundling issues with onnxruntime-web)
let VadModule = null;
async function loadVadModule() {
  if (VadModule) return VadModule;
  // Load self-contained WASM bundle (no dynamic import needed)
  await loadScript('/ort.wasm.bundle.min.mjs', true);
  await loadScript('/vad-bundle.min.js');
  VadModule = window.vad;
  return VadModule;
}

/**
 * Warm the VAD assets at page load so the first hands-free activation is
 * fast instead of a 30-60s download (iOS over the tunnel, 2026-08-03).
 * Fire-and-forget: never rejects, just warms the browser cache.
 */
export function preloadVadAssets() {
  try {
    loadVadModule().catch(() => {});
    // The onnx model + ort wasm are fetched by MicVAD.new — prefetch them
    // into the HTTP cache now.
    ['/silero_vad_v5.onnx', '/ort-wasm-simd-threaded.wasm', '/ort-wasm-simd.wasm']
      .forEach((p) => fetch(p, { cache: 'force-cache' }).catch(() => {}));
  } catch { /* preload is best-effort */ }
}

function loadScript(src, isModule = false) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) { resolve(); return; }
    const s = document.createElement('script');
    s.src = src;
    if (isModule) s.type = 'module';
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

export default function useSileroVAD({ handsFree, audioContext, onAudioBlob, onBargeIn, isPlaying = false }) {
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState(null);
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [maxDurationReached, setMaxDurationReached] = useState(false);
  const [volumeLevel, setVolumeLevel] = useState(0);
  const [initializing, setInitializing] = useState(false);
  const [stage, setStage] = useState('');

  const vadRef = useRef(null);
  const streamRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const silenceTimerRef = useRef(null);
  const isRecordingRef = useRef(false);
  const speakingRef = useRef(false);
  const runningRef = useRef(false);
  const durationTimerRef = useRef(null);
  const durationStartRef = useRef(0);
  const playingRef = useRef(false);
  const initializingRef = useRef(false);
  const stageRef = useRef('');
  const watchdogRef = useRef(null);
  const genRef = useRef(0); // generation token: kills stale in-flight inits
  const analyserRef = useRef(null);
  const rafRef = useRef(null);
  const volumeRef = useRef(0);
  const fallbackStreamRef = useRef(null); // fresh mic stream for recorder retry

  playingRef.current = isPlaying;

  const startRecording = useCallback(async () => {
    let stream = streamRef.current;
    if (!stream) return;
    chunksRef.current = [];
    // Intent-to-record, set BEFORE any await: the speech-end guard below
    // (and onSpeechStart's re-entry guard) rely on it being true while the
    // fresh-stream fallback is still arming.
    isRecordingRef.current = true;
    const mimeType = pickRecorderMime();

    // Chrome intermittently fails to START a MediaRecorder on the mic stream
    // the VAD worklet graph is consuming (NotSupportedError, observed
    // 2026-08-04 — speech detected, recording never starts, hands-free looks
    // dead). Retry with a FRESH mic stream — the tap-to-speak path, which
    // never hits this. Latency cost only in the failure case (the first
    // ~100-300ms of speech is not captured on retry).
    let mr;
    try {
      mr = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mr.start();
    } catch (err) {
      console.warn('VAD recorder failed on shared stream — retrying with a fresh mic stream', err);
      try {
        const fresh = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
        });
        // Speech may have ended while we awaited the stream — stop() was
        // already requested, so don't arm a recorder after the fact.
        if (!isRecordingRef.current) {
          fresh.getTracks().forEach((t) => t.stop());
          return;
        }
        fallbackStreamRef.current = fresh;
        mr = new MediaRecorder(fresh);
        mr.start();
      } catch (err2) {
        console.error('VAD recorder failed even on a fresh stream:', err2);
        if (fallbackStreamRef.current) {
          fallbackStreamRef.current.getTracks().forEach((t) => t.stop());
          fallbackStreamRef.current = null;
        }
        isRecordingRef.current = false;
        setMaxDurationReached(false);
        setIsRecording(false);
        setError(`[recording] Microphone recording failed to start: ${err2.message}`);
        return;
      }
    }

    mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
    mr.onstop = () => {
      // The fallback stream exists only for this recording — release the mic.
      if (fallbackStreamRef.current) {
        fallbackStreamRef.current.getTracks().forEach((t) => t.stop());
        fallbackStreamRef.current = null;
      }
      const blob = new Blob(chunksRef.current, { type: recorderBlobType(mr) });
      if (blob.size > 0 && onAudioBlob) onAudioBlob(blob);
    };
    mediaRecorderRef.current = mr;
    setError(null); // a recording started — clear any stale VAD error banner
    setIsRecording(true);
    setMaxDurationReached(false);
    setRecordingDuration(0);
    durationStartRef.current = Date.now();
    clearInterval(durationTimerRef.current);
    durationTimerRef.current = setInterval(() => {
      const elapsed = Date.now() - durationStartRef.current;
      setRecordingDuration(elapsed);
      if (elapsed >= MAX_RECORDING_MS) {
        setMaxDurationReached(true);
        clearInterval(durationTimerRef.current);
        const m = mediaRecorderRef.current;
        if (m && m.state !== 'inactive') m.stop();
        isRecordingRef.current = false;
        setIsRecording(false);
      }
    }, 1000);
  }, [onAudioBlob, setError]);

  const stopRecording = useCallback(() => {
    clearInterval(durationTimerRef.current);
    setRecordingDuration(0);
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== 'inactive') mr.stop();
    // Safety net: if the recorder never started, the fallback stream (if any)
    // would otherwise keep the mic hot.
    if (fallbackStreamRef.current) {
      fallbackStreamRef.current.getTracks().forEach((t) => t.stop());
      fallbackStreamRef.current = null;
    }
    isRecordingRef.current = false;
    setIsRecording(false);
  }, []);

  useEffect(() => {
    if (!handsFree) {
      cancelAnimationFrame(rafRef.current);
      if (analyserRef.current) { analyserRef.current.disconnect(); analyserRef.current = null; }
      if (vadRef.current) { vadRef.current.pause(); }
      clearTimeout(silenceTimerRef.current);
      clearInterval(durationTimerRef.current);
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      if (fallbackStreamRef.current) {
        fallbackStreamRef.current.getTracks().forEach((t) => t.stop());
        fallbackStreamRef.current = null;
      }
      setIsSpeaking(false); setIsRecording(false); setVolumeLevel(0); setInitializing(false);
      isRecordingRef.current = false; speakingRef.current = false;
      return;
    }
    runningRef.current = true;
    initializingRef.current = true;
    setInitializing(true);

    (async () => {
      // Generation token: every in-flight await checks it. Toggling off→on
      // (or the watchdog firing) bumps it, so a stale init can never finish
      // and leave an orphaned VAD holding the mic (review finding 2/5/7).
      const gen = ++genRef.current;
      const alive = () => runningRef.current && genRef.current === gen;
      const stopStream = () => {
        if (streamRef.current) {
          streamRef.current.getTracks().forEach((t) => t.stop());
          streamRef.current = null;
        }
      };

      // Stage-annotated errors + visible progress: the phone shows WHICH
      // step is running/failing (diagnostic, 2026-08-03 — iOS hands-free).
      const setStageNow = (s) => { stageRef.current = s; setStage(s); };
      setStageNow('loading VAD');

      // Watchdog: if init doesn't finish in 90s, surface the stuck stage
      // instead of "Starting mic…" forever (first load downloads ~10MB of
      // WASM over the tunnel — give it time).
      watchdogRef.current = setTimeout(() => {
        if (initializingRef.current) {
          setError(`[${stageRef.current}] init timed out after 90s — stuck (slow download or suspended audio)`);
          initializingRef.current = false;
          setInitializing(false);
          runningRef.current = false;
          genRef.current++; // invalidate the in-flight init
          stopStream();
        }
      }, 90000);

      try {
        const vadModule = await loadVadModule();
        if (!alive()) return;

        setStageNow('requesting mic');
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
        });
        if (!alive()) { stream.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = stream;

        setStageNow('resuming audio');
        const ctx = audioContext || new (window.AudioContext || window.webkitAudioContext)();
        if (ctx.state === 'suspended') {
          // iOS Safari: resume() outside a user gesture can stay pending
          // FOREVER — never await it unconditionally.
          try {
            await Promise.race([
              ctx.resume(),
              new Promise((_, rej) => setTimeout(() => rej(new Error('resume timed out — tap hands-free again to unlock audio')), 5000)),
            ]);
          } catch (e) {
            throw new Error(`resume: ${e.message}`);
          }
        }

        setStageNow('creating VAD');
        const vad = await vadModule.MicVAD.new({
          audioContext: ctx,
          model: 'v5',
          baseAssetPath: '/',
          onnxWASMBasePath: '/',
          startOnLoad: false,
          stream,
          onSpeechStart: () => {
            // Barge-in: user talks over the tutor → stop tutor audio immediately.
            // Recording starts right away; echoCancellation keeps the captured
            // mic stream free of the tutor's voice tail.
            if (playingRef.current && onBargeIn) onBargeIn.current?.();
            setIsSpeaking(true);
            speakingRef.current = true;
            clearTimeout(silenceTimerRef.current);
            if (!isRecordingRef.current) startRecording();
          },
          onSpeechEnd: () => {
            setIsSpeaking(false);
            speakingRef.current = false;
            clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = setTimeout(() => {
              if (isRecordingRef.current) stopRecording();
            }, SILENCE_TIMEOUT_MS);
          },
          onVADMisfire: () => {
            setIsSpeaking(false);
            speakingRef.current = false;
          },
        });

        setStageNow('starting VAD');
        vadRef.current = vad;
        await vad.start();
        if (!alive()) { vad.destroy(); stopStream(); return; }

        // Set up a passive volume analyser from the same mic stream
        // Connects a separate MediaStreamSource so it doesn't interfere with the VAD
        const sourceNode = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.8;
        sourceNode.connect(analyser);
        analyserRef.current = analyser;

        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        let lastUpdate = performance.now();

        function tick(now) {
          if (!runningRef.current) return;
          analyser.getByteTimeDomainData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) {
            const val = dataArray[i] / 128 - 1;
            sum += val * val;
          }
          const rms = Math.sqrt(sum / dataArray.length);
          // Scale up for mic-level sensitivity, clamp to 0-1
          volumeRef.current = Math.min(1, rms * 2.5);
          if (now - lastUpdate > 80) {
            setVolumeLevel(volumeRef.current);
            lastUpdate = now;
          }
          rafRef.current = requestAnimationFrame(tick);
        }
        rafRef.current = requestAnimationFrame(tick);

        if (!alive()) { vad.destroy(); stopStream(); return; }
        clearTimeout(watchdogRef.current);
        setError(null);
        initializingRef.current = false;
        setInitializing(false);
      } catch (err) {
        const where = stageRef.current;
        if (err.name === 'NotFoundError') {
          setError(`[${where}] No microphone found. Connect a mic and try again.`);
        } else if (err.name === 'NotAllowedError') {
          setError(`[${where}] Microphone permission denied. Allow mic access in browser settings.`);
        } else if (err.name === 'NotReadableError') {
          setError(`[${where}] Mic is in use by another app. Close other apps and try again.`);
        } else {
          setError(`[${where}] ${err.name}: ${err.message}`);
        }
        clearTimeout(watchdogRef.current);
        initializingRef.current = false;
        setInitializing(false);
        runningRef.current = false;
        genRef.current++;
        stopStream(); // never leave the mic light on after a failed init
      }
    })();

    return () => {
      runningRef.current = false;
      clearTimeout(watchdogRef.current);
      initializingRef.current = false;
      cancelAnimationFrame(rafRef.current);
      if (analyserRef.current) { analyserRef.current.disconnect(); analyserRef.current = null; }
      clearTimeout(silenceTimerRef.current);
      clearInterval(durationTimerRef.current);
      if (vadRef.current) { vadRef.current.destroy(); vadRef.current = null; }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      if (fallbackStreamRef.current) {
        fallbackStreamRef.current.getTracks().forEach((t) => t.stop());
        fallbackStreamRef.current = null;
      }
      if (streamRef.current) { streamRef.current.getTracks().forEach(t => t.stop()); streamRef.current = null; }
      setIsSpeaking(false); setIsRecording(false); setVolumeLevel(0); setInitializing(false);
      isRecordingRef.current = false; speakingRef.current = false;
    };
  }, [handsFree, audioContext, onAudioBlob, onBargeIn, startRecording, stopRecording]);

  return { isSpeaking, isRecording, error, recordingDuration, maxDurationReached, volumeLevel, initializing, stage };
}
