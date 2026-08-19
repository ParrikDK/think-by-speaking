// Realtime voice engine hook (v11 M2, 2026-08-08).
//
// Faithful port of the live-tested spike page
// (spike/qwen-realtime/static/index.html) onto React: AudioWorklet mic
// capture → 16 kHz PCM16 upstream, 24 kHz gapless playback with a 100 ms
// jitter buffer, zero-gain worklet routing (NEVER mic → speakers — that
// was the first-syllable stutter bug), iOS gesture unlock, PTT (hold /
// slide-off cancel / spacebar / <0.3 s drop) + hands-free (server
// semantic_vad), barge-in in both modes, single-replay rule, typed input
// with a pre-connect queue, reconnect with backoff, session-cap rollover
// (close 4000 → silent reconnect with cont=1) and quota card (close 4001).
//
// All audio/WS machinery lives in refs (created once); React state only
// carries what the screen renders: session flags, the message list, meter
// level, banner, quota card, latency log. Banner strings are i18n KEYS —
// the screen translates with t(banner, banner) so raw server messages
// still pass through untranslated.
import { useEffect, useRef, useState } from 'react';
import { getToken, realtimeWsUrl } from '../api';
import { pitchVariance } from '../utils/audioMetrics';

const MAX_RECONNECTS = 3;

// AudioWorklet source (inline via Blob URL): forwards Float32 blocks,
// batched ~4k samples.
const WORKLET_SRC = `
class PCMWorklet extends AudioWorkletProcessor {
  constructor() { super(); this.chunks = []; this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) {
      this.chunks.push(ch.slice(0)); this.n += ch.length;
      if (this.n >= 4096) {
        const out = new Float32Array(this.n);
        let o = 0;
        for (const c of this.chunks) { out.set(c, o); o += c.length; }
        this.port.postMessage(out, [out.buffer]);
        this.chunks = []; this.n = 0;
      }
    }
    return true;
  }
}
registerProcessor('pcm-worklet', PCMWorklet);
`;

// Linear-interp decimation to 16 kHz + Float32 -> PCM16 LE. Same as the rig.
function downsampleToPCM16(input, srcRate, dstRate) {
  const ratio = srcRate / dstRate;
  const outLen = Math.floor(input.length / ratio);
  const out = new Int16Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio;
    const i0 = Math.floor(pos);
    const frac = pos - i0;
    const next = input[Math.min(i0 + 1, input.length - 1)];
    const s = input[i0] + (next - input[i0]) * frac;
    const c = Math.max(-1, Math.min(1, s));
    out[i] = c < 0 ? c * 0x8000 : c * 0x7FFF;
  }
  return out;
}

// PCM16 -> WAV wrapper for the Replay button (blob URL + <audio>).
function makeWav(pcmBytes, sampleRate) {
  const buf = new ArrayBuffer(44 + pcmBytes.length);
  const v = new DataView(buf);
  const wstr = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
  wstr(0, 'RIFF'); v.setUint32(4, 36 + pcmBytes.length, true); wstr(8, 'WAVE');
  wstr(12, 'fmt '); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);                 // PCM
  v.setUint16(22, 1, true);                 // mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);    // byte rate
  v.setUint16(32, 2, true);                 // block align
  v.setUint16(34, 16, true);                // bits
  wstr(36, 'data'); v.setUint32(40, pcmBytes.length, true);
  new Uint8Array(buf, 44).set(pcmBytes);
  return buf;
}

export default function useRealtime({ lang, level, scenarioId, native, profile, voice, speakCardRef }) {
  // Params are fixed for a mounted screen; the ref keeps the engine
  // closures (created once) reading the latest values regardless.
  const paramsRef = useRef({ lang, level, scenarioId, native, profile, voice });
  paramsRef.current = { lang, level, scenarioId, native, profile, voice };

  // ── React state (rendered by the screen) ──
  const [mode, setModeState] = useState(() => localStorage.getItem('vtalk-mode') || 'ptt');
  const [sessionActive, setSessionActive] = useState(false);
  const [wsOpen, setWsOpen] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [tutorSpeaking, setTutorSpeaking] = useState(false);
  const [pttHeld, setPttHeld] = useState(false);
  const [pttCancel, setPttCancelState] = useState(false);
  const [messages, setMessages] = useState([]);
  const [activeTutorId, setActiveTutorId] = useState(null);
  const [banner, setBanner] = useState(null);      // i18n key or raw server message
  const [quotaCard, setQuotaCard] = useState(null); // null | 'guest' | 'user'
  const [micLevel, setMicLevel] = useState(0);
  const [latency, setLatency] = useState([]);

  const engineRef = useRef(null);
  if (!engineRef.current) {
    // ── Engine refs (the spike's module-level `let`s) ──
    const wsRef = { current: null };
    const sessionActiveRef = { current: false };
    const manualCloseRef = { current: false };
    const reconnectAttemptsRef = { current: 0 };
    const contRef = { current: false };        // set after the first 4000 rollover
    const isGuestRef = { current: true };      // token presence at connect time
    const micCtxRef = { current: null };
    const micStreamRef = { current: null };
    const micNodeRef = { current: null };
    const micBlockedRef = { current: false };  // v13: mic unavailable → typed+TTS still work
    const playCtxRef = { current: null };
    const playQueueRef = { current: [] };      // AudioBufferSourceNodes scheduled/playing
    const nextPlayTimeRef = { current: 0 };    // gapless scheduling cursor (playCtx time)
    const modeRef = { current: mode };
    const pttHeldRef = { current: false };
    const pttCancelRef = { current: false };
    const pttBytesRef = { current: 0 };
    const pttPcmRef = { current: [] };  // Int16Array chunks of the held turn (v13.1 pitch)
    const turnRefRef = { current: null };      // {t, label} waiting for first tutor audio
    const respondingRef = { current: false };
    const recChunksRef = { current: null };    // PCM chunks of the in-flight response
    const currentTutorIdRef = { current: null };
    const turnRegistryRef = { current: new Map() }; // server turn -> {userId, tutorId}
    const replayByIdRef = { current: new Map() };   // message id -> sealed PCM chunks
    const typedQueueRef = { current: [] };     // texts typed before the session was open
    const msgSeqRef = { current: 1 };
    const currentReplayRef = { current: null }; // {audio, url}
    const reconnectTimerRef = { current: null };

    const nextMsgId = () => msgSeqRef.current++;

    // ── message list helpers ──
    const updateMessage = (id, patch) => {
      setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
    };

    const registerTurn = (turn, key, id) => {
      if (turn == null) return;
      const rec = turnRegistryRef.current.get(turn) || {};
      rec[key] = id;
      turnRegistryRef.current.set(turn, rec);
    };

    const ensureTutorBubble = () => {
      if (currentTutorIdRef.current != null) return currentTutorIdRef.current;
      const id = nextMsgId();
      currentTutorIdRef.current = id;
      setActiveTutorId(id);
      setMessages((prev) => [...prev, {
        id, role: 'tutor', text: '', replay: false, turn: null,
      }]);
      return id;
    };

    // Seal the in-flight response: freeze its audio chunks for Replay.
    const sealTutorBubble = () => {
      const id = currentTutorIdRef.current;
      const chunks = recChunksRef.current;
      currentTutorIdRef.current = null;
      recChunksRef.current = null;
      setActiveTutorId(null);
      if (id == null) return;
      if (chunks && chunks.length) replayByIdRef.current.set(id, chunks);
      updateMessage(id, { replay: !!(chunks && chunks.length) });
    };

    // Shared renderer for ASR transcripts and typed-text echoes. NOTE: an
    // ASR completed event can arrive AFTER the tutor's reply has already
    // started streaming — insert the user bubble BEFORE the in-flight
    // tutor bubble so the conversation reads in order (spike, 2026-08-06).
    const renderUserTranscript = (ev) => {
      const text = (ev.transcript || '').trim();
      if (!text && !ev.transcript_unclear) return;
      const id = nextMsgId();
      const msg = {
        id,
        role: 'user',
        text: ev.transcript_unclear ? '' : text,
        unclear: !!ev.transcript_unclear,
        feedback: null,
        turn: ev.turn ?? null,
      };
      registerTurn(ev.turn, 'userId', id);
      const tutorId = currentTutorIdRef.current;
      setMessages((prev) => {
        const idx = tutorId == null ? -1 : prev.findIndex((m) => m.id === tutorId);
        if (idx === -1) return [...prev, msg];
        const next = prev.slice();
        next.splice(idx, 0, msg);
        return next;
      });
    };

    // ── playback (24 kHz) ──
    const ensurePlayCtx = () => {
      if (playCtxRef.current) return;
      try { playCtxRef.current = new AudioContext({ sampleRate: 24000 }); }
      catch (e) { playCtxRef.current = new AudioContext(); } // buffer at 24k still resamples on playback
    };

    // iOS/Safari: an AudioContext created (or left suspended) outside a
    // user gesture produces a silent first reply (v9 bug F2). start() is
    // always reached from a tap/click, so create + resume both contexts
    // there.
    const unlockAudio = () => {
      ensurePlayCtx();
      if (playCtxRef.current.state === 'suspended') playCtxRef.current.resume();
      if (!micCtxRef.current) micCtxRef.current = new AudioContext();
      if (micCtxRef.current.state === 'suspended') micCtxRef.current.resume();
    };

    const playPCM = (arrayBuffer) => {
      ensurePlayCtx();
      const playCtx = playCtxRef.current;
      const int16 = new Int16Array(arrayBuffer);
      const f32 = new Float32Array(int16.length);
      for (let i = 0; i < int16.length; i++) f32[i] = int16[i] / 32768;
      const buf = playCtx.createBuffer(1, f32.length, 24000);
      buf.copyToChannel(f32, 0);
      const node = playCtx.createBufferSource();
      node.buffer = buf;
      node.connect(playCtx.destination);
      // Small jitter buffer (100 ms): upstream sends audio in bursts faster
      // than realtime — a 30 ms floor let the first chunk underrun before
      // the second burst landed (spike, 2026-08-07).
      const t = Math.max(playCtx.currentTime + 0.10, nextPlayTimeRef.current);
      node.start(t);
      nextPlayTimeRef.current = t + buf.duration;
      playQueueRef.current.push(node);
      node.onended = () => {
        playQueueRef.current = playQueueRef.current.filter((n) => n !== node);
      };
    };

    const flushPlayback = () => {
      for (const n of playQueueRef.current) { try { n.stop(); } catch (e) { /* already stopped */ } }
      playQueueRef.current = [];
      nextPlayTimeRef.current = 0;
    };

    // ── replay: only one at a time, and never alongside live audio —
    // starting a replay cuts the live queue AND any in-flight response
    // (mutual exclusion with the response.created handler, which stops the
    // replay when a new reply starts). Deliberately NOT cut by
    // speech_started: the user speaks along with a looping replay to mimic
    // pronunciation. Local-only playback — the mic/session are unaffected
    // (echo cancellation covers speaker playback).
    const stopCurrentReplay = () => {
      const cur = currentReplayRef.current;
      if (!cur) return;
      try { cur.audio.pause(); } catch (e) { /* not started */ }
      URL.revokeObjectURL(cur.url);
      currentReplayRef.current = null;
    };

    const replayChunks = (chunks) => {
      const total = chunks.reduce((n, c) => n + c.byteLength, 0);
      if (!total) return;
      flushPlayback();                         // cut any live tutor audio still in the queue
      stopCurrentReplay();                     // cut the previous replay, if one is playing
      if (respondingRef.current) sendJSON({ type: 'response.cancel' });  // kill the in-flight reply so its tail can't re-schedule
      const pcm = new Uint8Array(total);
      let o = 0;
      for (const c of chunks) { pcm.set(new Uint8Array(c), o); o += c.byteLength; }
      const url = URL.createObjectURL(new Blob([makeWav(pcm, 24000)], { type: 'audio/wav' }));
      stopCurrentReplay();
      const audio = new Audio(url);
      const entry = { audio, url };
      currentReplayRef.current = entry;
      audio.onended = () => {
        if (currentReplayRef.current === entry) currentReplayRef.current = null;
        URL.revokeObjectURL(url);
      };
      audio.onerror = () => {
        if (currentReplayRef.current === entry) currentReplayRef.current = null;
        URL.revokeObjectURL(url);
        setBanner('rt.replay_failed');
      };
      audio.play().catch(() => setBanner('rt.replay_blocked'));
    };

    // ── volume meter ──
    const updateMeter = (f32) => {
      let sum = 0;
      let n = 0;
      for (let i = 0; i < f32.length; i += 4) { sum += f32[i] * f32[i]; n++; } // stride sample is plenty
      const rms = Math.sqrt(sum / Math.max(1, n));
      // attack fast, decay slow (spike: max(level, prev * 0.82))
      setMicLevel((prev) => Math.max(Math.min(1, rms * 5), prev * 0.82));
    };

    // ── mic capture ──
    const startMic = async () => {
      if (micStreamRef.current) return;      // keep the mic across WS reconnects
      micStreamRef.current = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
      });
      // Reuse the context unlockAudio() may have created in the tap gesture.
      if (!micCtxRef.current) micCtxRef.current = new AudioContext(); // device rate, e.g. 48 kHz
      if (micCtxRef.current.state === 'suspended') await micCtxRef.current.resume();
      const micCtx = micCtxRef.current;
      const srcRate = micCtx.sampleRate;
      await micCtx.audioWorklet.addModule(
        URL.createObjectURL(new Blob([WORKLET_SRC], { type: 'application/javascript' })));
      const src = micCtx.createMediaStreamSource(micStreamRef.current);
      const micNode = new AudioWorkletNode(micCtx, 'pcm-worklet');
      micNodeRef.current = micNode;
      micNode.port.onmessage = (e) => {
        updateMeter(e.data);
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (modeRef.current === 'ptt' && !pttHeldRef.current) return; // ptt: send only while held
        const pcm = downsampleToPCM16(e.data, srcRate, 16000);
        if (pcm.length) {
          if (modeRef.current === 'ptt') {
            pttBytesRef.current += pcm.byteLength;
            pttPcmRef.current.push(pcm);       // keep the bytes for pitch analysis
          }
          ws.send(pcm.buffer);                 // binary frame = raw PCM16 LE @16 kHz
        }
      };
      src.connect(micNode);
      // Keep the worklet pulled WITHOUT audible monitoring: route through a
      // zero-gain node. (Connecting micNode straight to destination = live
      // mic monitoring through the speakers: the tutor's own audio
      // re-entered via the mic and was replayed through that loop — the
      // "first syllable repeats for 1-2 s" stutter, until the echo
      // canceller adapted. 2026-08-07)
      const muteGain = micCtx.createGain();
      muteGain.gain.value = 0;
      micNode.connect(muteGain);
      muteGain.connect(micCtx.destination);
    };

    const stopMic = () => {
      if (micNodeRef.current) { micNodeRef.current.disconnect(); micNodeRef.current = null; }
      if (micCtxRef.current) { micCtxRef.current.close(); micCtxRef.current = null; }
      if (micStreamRef.current) {
        micStreamRef.current.getTracks().forEach((tr) => tr.stop());
        micStreamRef.current = null;
      }
      setMicLevel(0);
    };

    // ── latency log (debug drawer) ──
    const addLatency = (ms, label) => {
      setLatency((prev) => [{
        id: Date.now() + Math.random(),
        text: `turn @${new Date().toLocaleTimeString()} — ${ms} ms (from ${label})`,
      }, ...prev].slice(0, 50));
    };

    const sendJSON = (obj) => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
    };

    // ── upstream events ──
    const friendlyError = (ev) => {
      const m = (ev.error && ev.error.message) || ev.message || '';
      // Server-config errors stay as raw English (developer-facing, like
      // the spike); anything else renders through the generic key.
      if (/DASHSCOPE_API_KEY|failed to connect to DashScope/i.test(m)) return m;
      return m ? m : 'rt.error_generic';
    };

    const handleEvent = (ev) => {
      switch (ev.type) {
        case 'session.created':
        case 'session.updated':
          break;

        case 'input_audio_buffer.speech_started':
          flushPlayback();                       // barge-in: cut tutor audio immediately
          sealTutorBubble();
          turnRefRef.current = null;
          break;

        case 'input_audio_buffer.speech_stopped':
          turnRefRef.current = { t: performance.now(), label: 'speech_stopped' };
          break;

        case 'response.created':
          sealTutorBubble();                     // previous turn, if done never arrived
          stopCurrentReplay();                   // live tutor audio takes precedence
          respondingRef.current = true;
          recChunksRef.current = [];
          if (!turnRefRef.current) turnRefRef.current = { t: performance.now(), label: 'response.created' };
          break;

        case 'response.done':
          respondingRef.current = false;
          sealTutorBubble();
          break;

        // User transcript appears when the turn completes (deltas are preview-only).
        case 'conversation.item.input_audio_transcription.completed':
          renderUserTranscript(ev);
          break;

        // Typed input: the proxy echoes it back; the bubble renders only from this.
        case 'proxy.user_transcript':
          renderUserTranscript(ev);
          break;

        // v13.1 moderator: a neutral host line — its own ⚖️ bubble.
        case 'proxy.moderator': {
          const id = nextMsgId();
          setMessages((prev) => [...prev, {
            id, role: 'moderator', text: ev.text || '', replay: false,
          }]);
          break;
        }

        // Async debate feedback card for a finished turn (v13): attach to
        // that turn's user bubble.
        case 'proxy.feedback': {
          const rec = turnRegistryRef.current.get(ev.turn);
          if (rec && rec.userId != null) {
            const feedback = {
              stance: ev.stance || 'partially_agree',
              score: Number(ev.score) || 50,
              score_delta: Number(ev.score_delta) || 0,
              counter: ev.counter || '',
              evidence: ev.evidence || '',
              next: ev.next || '',
            };
            updateMessage(rec.userId, { feedback });
            // v13.2 voice-first: auto-read the card the moment it lands.
            // speakCardRef (stable ref supplied by the screen) holds the
            // latest speak function — it checks the voice-first toggle
            // and plays via the shared card-read controller in DebateCard,
            // so a new read barges any previous one. Mirror RtBubble:
            // only speak when a real card (rebuttal/evidence) renders,
            // not the light ack.
            if ((feedback.counter || feedback.evidence) && speakCardRef?.current) {
              speakCardRef.current(feedback);
            }
          }
          break;
        }

        case 'response.audio_transcript.delta': {
          const id = ensureTutorBubble();
          const d = ev.delta || '';
          if (d) {
            setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, text: m.text + d } : m)));
          }
          break;
        }
        case 'response.audio_transcript.done': {
          const id = currentTutorIdRef.current;
          if (id != null && ev.transcript) {
            updateMessage(id, { text: ev.transcript });
            registerTurn(ev.turn, 'tutorId', id);
          }
          break;
        }

        // Silent rollover marker — the close-4000 path does the reconnect.
        case 'proxy.session_cap':
          break;

        // Quota/trial used up mid-session; the 4001 close follows and
        // tears down. Set the card here too in case the close is lost.
        case 'proxy.quota_exhausted':
          setQuotaCard(isGuestRef.current ? 'guest' : 'user');
          break;

        case 'error':
          setBanner(friendlyError(ev));
          break;

        default:
          break;
      }
    };

    const onAudioFrame = (buf) => {
      // While a replay plays, ignore straggler deltas of a cancelled
      // response (sent upstream by replayChunks) — they'd otherwise
      // re-schedule over the replay. A fresh response stops the replay via
      // response.created before its deltas flow.
      if (currentReplayRef.current) return;
      if (turnRefRef.current) {
        addLatency(Math.round(performance.now() - turnRefRef.current.t), turnRefRef.current.label);
        turnRefRef.current = null;
      }
      ensureTutorBubble();
      if (recChunksRef.current) recChunksRef.current.push(buf); // accumulate for Replay
      playPCM(buf);
    };

    // ── connect / disconnect ──
    const connect = () => {
      const p = paramsRef.current;
      const url = realtimeWsUrl({
        lang: p.lang,
        level: p.level,
        mode: modeRef.current,
        scenarioId: p.scenarioId,
        native: p.native,
        cont: contRef.current,
        profile: p.profile,
        voice: p.voice,
      });
      isGuestRef.current = !getToken();
      turnRegistryRef.current = new Map();  // server turn numbering restarts per connection
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttemptsRef.current = 0;
        setReconnecting(false);
        setWsOpen(true);
        // Flush texts typed before the session was open — typed debate and
        // TTS playback never depend on the mic (v13: mic is optional).
        while (typedQueueRef.current.length && wsRef.current === ws
               && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'user_text', text: typedQueueRef.current.shift() }));
        }
        // Mic is best-effort: on failure the session STAYS OPEN with a
        // banner; a later user gesture (pttDown) can retry it.
        if (!micStreamRef.current) {
          startMic()
            .then(() => { micBlockedRef.current = false; })
            .catch(() => {
              micBlockedRef.current = true;
              setBanner('rt.mic_blocked');
            });
        }
      };
      ws.onmessage = (m) => {
        if (typeof m.data === 'string') {
          try { handleEvent(JSON.parse(m.data)); } catch (e) { /* malformed frame */ }
        } else {
          onAudioFrame(m.data);                  // binary = tutor PCM16 @24 kHz
        }
      };
      ws.onclose = (e) => {
        if (wsRef.current === ws) wsRef.current = null;
        const wasSession = sessionActiveRef.current;
        respondingRef.current = false;
        flushPlayback();
        sealTutorBubble();
        setWsOpen(false);
        if (!wasSession) { setReconnecting(false); return; }
        if (manualCloseRef.current || e.code === 1008) { // 1008 = bad params/key: no point retrying
          engine.end();
          return;
        }
        if (e.code === 4001) {                 // quota/trial exhausted → friendly card
          setQuotaCard(isGuestRef.current ? 'guest' : 'user');
          engine.end();
          return;
        }
        if (e.code === 4000) {
          // Session audio cap — silent rollover: reconnect at once with
          // cont=1 (server skips the greeting); chat stays visible.
          contRef.current = true;
          if (sessionActiveRef.current && !wsRef.current) connect();
          return;
        }
        if (reconnectAttemptsRef.current < MAX_RECONNECTS) {
          reconnectAttemptsRef.current++;
          setReconnecting(true);
          reconnectTimerRef.current = setTimeout(() => {
            if (sessionActiveRef.current && !wsRef.current) connect();
          }, 1500);
        } else {
          setBanner('rt.reconnect_failed');
          engine.end();
        }
      };
      ws.onerror = () => { /* onclose follows with the real teardown */ };
    };

    const engine = {
      start() {
        setBanner(null);
        setQuotaCard(null);
        unlockAudio();          // iOS gesture window — create/resume audio contexts
        sessionActiveRef.current = true;
        setSessionActive(true);
        manualCloseRef.current = false;
        reconnectAttemptsRef.current = 0;
        setReconnecting(false);
        connect();
      },

      end() {
        sessionActiveRef.current = false;
        setSessionActive(false);
        manualCloseRef.current = true;
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
          reconnectTimerRef.current = null;
        }
        const ws = wsRef.current;
        if (ws) { try { ws.close(); } catch (e) { /* already closed */ } wsRef.current = null; }
        respondingRef.current = false;
        setTutorSpeaking(false);
        setReconnecting(false);
        setWsOpen(false);
        pttHeldRef.current = false;
        setPttHeld(false);
        stopMic();
        flushPlayback();
        sealTutorBubble();
      },

      interrupt() {
        flushPlayback();
        sealTutorBubble();
        sendJSON({ type: 'response.cancel' });
        setTutorSpeaking(false);
      },

      // ── push-to-talk ──
      pttDown() {
        if (modeRef.current !== 'ptt' || pttHeldRef.current) return;
        if (!sessionActiveRef.current) engine.start(); // connects; the send gate opens once WS is OPEN
        if (micBlockedRef.current && !micStreamRef.current) {
          // A hold is a user gesture — the browser may now allow the mic.
          startMic().then(() => {
            micBlockedRef.current = false;
            setBanner(null);
          }).catch(() => setBanner('rt.mic_blocked'));
        }
        pttHeldRef.current = true;
        setPttHeld(true);
        pttCancelRef.current = false;
        setPttCancelState(false);
        pttBytesRef.current = 0;
        pttPcmRef.current = [];
        if (playQueueRef.current.length > 0) {         // holding to talk = barge-in
          flushPlayback();
          sealTutorBubble();
          sendJSON({ type: 'response.cancel' });
          setTutorSpeaking(false);
        }
        sendJSON({ type: 'input_audio_buffer.clear' }); // drop anything stale
      },

      pttRelease() {
        if (!pttHeldRef.current) return;
        pttHeldRef.current = false;
        setPttHeld(false);
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (pttCancelRef.current || pttBytesRef.current < 9600) {
          // slid off, or too short (<~0.3 s): drop it
          ws.send(JSON.stringify({ type: 'input_audio_buffer.clear' }));
          return;
        }
        // v13.1 audio pillar: measure the held turn (pitch variance via
        // autocorrelation F0; duration from the byte count) and send it
        // with the commit — the judge attaches pace + pitch to the card.
        try {
          const chunks = pttPcmRef.current;
          const total = chunks.reduce((n, a) => n + a.length, 0);
          const secs = total / 32000; // PCM16 @16 kHz
          let pitchVar = 0;
          if (total >= 4096) {
            const mono = new Float32Array(total);
            let o = 0;
            for (const c of chunks) { for (let i = 0; i < c.length; i++) mono[o++] = c[i] / 32768; }
            pitchVar = Math.round(pitchVariance(mono, 16000) * 10) / 10;
          }
          if (secs > 0.5 || pitchVar > 0) {
            ws.send(JSON.stringify({
              type: 'turn_metrics',
              pitch_var: pitchVar,
              secs: Math.round(secs * 10) / 10,
            }));
          }
        } catch (e) { /* metrics are best-effort */ }
        pttPcmRef.current = [];
        turnRefRef.current = { t: performance.now(), label: 'commit' };
        ws.send(JSON.stringify({ type: 'input_audio_buffer.commit' }));
        ws.send(JSON.stringify({ type: 'response.create' }));
      },

      // Slide off = cancel (WeChat-style); slide back on re-arms the send.
      pttSetCancel(v) {
        if (!pttHeldRef.current) return;
        pttCancelRef.current = v;
        setPttCancelState(v);
      },

      setMode(next) {
        const m = next === 'handsfree' ? 'handsfree' : 'ptt';
        if (m === modeRef.current) return;
        modeRef.current = m;
        setModeState(m);
        localStorage.setItem('vtalk-mode', m);
        // The VAD config lives in session.update, so a live session can't
        // change modes — reconnect (the spike's behavior).
        if (sessionActiveRef.current) {
          engine.end();
          engine.start();
        }
      },

      // ── typed input (same send path as the starter chips) ──
      sendText(text) {
        const value = (text || '').trim();
        if (!value) return;
        if (!sessionActiveRef.current) {
          typedQueueRef.current.push(value);
          engine.start();                        // queue flushes in ws.onopen once the mic is up
          return;
        }
        const ws = wsRef.current;
        if (ws && ws.readyState === WebSocket.OPEN) {
          if (playQueueRef.current.length > 0) { // typed barge-in: same flush as the mic path
            flushPlayback();
            sealTutorBubble();
            ws.send(JSON.stringify({ type: 'response.cancel' }));
            setTutorSpeaking(false);
          }
          ws.send(JSON.stringify({ type: 'user_text', text: value }));
        } else {
          typedQueueRef.current.push(value);     // reconnecting: flushes on next onopen
        }
      },

      replay(id) {
        const chunks = replayByIdRef.current.get(id);
        if (chunks && chunks.length) replayChunks(chunks);
      },

      clearBanner() { setBanner(null); },

      // Full teardown for unmount: everything end() does, plus the playback
      // context and any replay in flight.
      dispose() {
        engine.end();
        stopCurrentReplay();
        if (playCtxRef.current) { playCtxRef.current.close(); playCtxRef.current = null; }
      },

      // Speaking = anything in the gapless playback queue (the spike's
      // 120 ms tick keeps the UI in sync with actual audio).
      isSpeaking: () => playQueueRef.current.length > 0,
      modeRef,
    };
    engineRef.current = engine;
  }
  const engine = engineRef.current;
  engine.modeRef.current = mode;

  // Speaking tick + unmount teardown.
  useEffect(() => {
    const id = setInterval(() => {
      const speaking = engine.isSpeaking();
      setTutorSpeaking((prev) => (prev === speaking ? prev : speaking));
    }, 120);
    return () => {
      clearInterval(id);
      engine.dispose();
    };
  }, [engine]);

  return {
    // state
    mode,
    sessionActive,
    wsOpen,
    reconnecting,
    tutorSpeaking,
    pttHeld,
    pttCancel,
    messages,
    activeTutorId,
    banner,
    quotaCard,
    micLevel,
    latency,
    // actions
    start: engine.start,
    end: engine.end,
    interrupt: engine.interrupt,
    pttDown: engine.pttDown,
    pttRelease: engine.pttRelease,
    pttSetCancel: engine.pttSetCancel,
    setMode: engine.setMode,
    sendText: engine.sendText,
    replay: engine.replay,
    clearBanner: engine.clearBanner,
  };
}
