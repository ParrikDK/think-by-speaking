import { useCallback, useEffect, useRef, useState } from 'react';
import { hostLine, setupVoiceParse } from '../api';
import { useT } from '../i18n/useI18n';

/**
 * Voice-guided setup (v13.1, "grandma mode" v1) — the host speaks numbered
 * menus, the learner answers by voice, STT + LLM map the answer.
 * Research-informed (2026-08-19): numbered verbal options, beep-then-speak,
 * plain language, error-tolerant retries.
 */
const STEPS = ['subject', 'depth', 'style'];

const QUESTIONS = {
  subject:
    "Welcome! Let's set up your debate by voice. Say the subject you'd like to debate — for example, AI jobs, social media, remote work, or say free debate.",
  depth:
    "How deep should we go? Say one for Basics, two for Balanced, or three for Expert.",
  style:
    "How should I push back? Say one for Devil's advocate, two for Socratic, three for Heckler, four for Boardroom, or five for Encouraging.",
  retry: "I didn't quite catch that. Say the number, like one or two, or repeat the subject name.",
  done: 'All set. Starting your debate now.',
};

export default function VoiceSetupScreen({ scenarios, onBack, onStart }) {
  const t = useT('en');
  const [stepIdx, setStepIdx] = useState(0);
  const [answers, setAnswers] = useState({});
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false); // parsing / host talking
  const [retries, setRetries] = useState(0);
  const [status, setStatus] = useState('');
  const recorderRef = useRef(null);
  const audioRef = useRef(null);

  const say = useCallback(async (text) => {
    setBusy(true);
    try {
      const { audio_base64 } = await hostLine(text);
      const audio = new Audio(`data:audio/mpeg;base64,${audio_base64}`);
      audioRef.current = audio;
      await new Promise((resolve) => {
        audio.onended = resolve;
        audio.onerror = resolve;
        audio.play().catch(resolve);
      });
    } catch {
      /* host speech is best-effort — the on-screen text still shows */
    } finally {
      setBusy(false);
    }
  }, []);

  const currentStep = STEPS[stepIdx];

  useEffect(() => {
    if (stepIdx >= STEPS.length) {
      say(QUESTIONS.done).then(() => {
        const s = answers.subject;
        const subjectObj = s && s !== 'free'
          ? scenarios.find((x) => x.id === s) || null
          : null;
        onStart({
          langObj: { code: 'en', name: 'English', native_name: 'English', realtime: false },
          lvl: answers.depth || 'intermediate',
          scenarioObj: subjectObj,
          profile: { style: answers.style || 'encouraging', interests: [] },
        });
      });
      return;
    }
    say(QUESTIONS[currentStep]);
    setStatus('');
  }, [stepIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleRecord = useCallback(async () => {
    if (recording) {
      // stop + parse
      setRecording(false);
      setBusy(true);
      setStatus('listening');
      try {
        recorderRef.current?.stop();
        const blob = await new Promise((resolve) => {
          const rec = recorderRef.current;
          rec.onstop = () => resolve(rec.blob || null);
        });
        if (!blob) throw new Error('no recording');
        const res = await setupVoiceParse(currentStep, blob);
        if (res.unclear) {
          if (retries < 2) {
            setRetries((r) => r + 1);
            setStatus('unclear');
            await say(QUESTIONS.retry);
            setStatus('');
          } else {
            // fall back to a sensible default rather than blocking
            const fallback = {
              subject: { choice: 'free', label: 'Free debate' },
              depth: { choice: 'intermediate', label: 'Balanced' },
              style: { choice: 'encouraging', label: 'Encouraging' },
            }[currentStep];
            setAnswers((a) => ({ ...a, [currentStep]: fallback.choice }));
            setRetries(0);
            setStepIdx((i) => i + 1);
          }
        } else {
          setAnswers((a) => ({ ...a, [currentStep]: res.choice }));
          setRetries(0);
          setStepIdx((i) => i + 1);
        }
      } catch (e) {
        console.error('voice setup failed:', e);
        setStatus('error');
      } finally {
        setBusy(false);
      }
      return;
    }
    // start recording (tap-to-record; beep cue would come from the host)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      rec.chunks = [];
      rec.ondataavailable = (e) => rec.chunks.push(e.data);
      rec.onstop = () => {
        rec.blob = new Blob(rec.chunks, { type: rec.mimeType || 'audio/webm' });
        stream.getTracks().forEach((tr) => tr.stop());
      };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);
      setStatus('');
    } catch {
      setStatus('mic_blocked');
    }
  }, [recording, currentStep, retries, say, scenarios, answers]);

  const stepLabel = {
    subject: '1 / 3 — Subject',
    depth: '2 / 3 — Depth',
    style: '3 / 3 — Style',
  }[currentStep] || '';

  const statusText = {
    listening: 'Listening to your answer…',
    unclear: 'Not quite — try again.',
    mic_blocked: 'Microphone blocked — allow it in the address bar.',
    error: 'Something went wrong — tap the mic to retry.',
  }[status] || '';

  return (
    <div className="screen setup-screen">
      <nav className="welcome-nav">
        <span className="topbar-spacer" />
        <button className="btn btn-ghost btn-sm" onClick={onBack}>{t('common.back')}</button>
      </nav>
      <div className="setup-body" style={{ alignItems: 'center', textAlign: 'center' }}>
        <h2 className="setup-title">🎙️ {t('voice_setup.title')}</h2>
        <p className="setup-hint">{stepLabel}</p>

        <button
          className="btn btn-primary setup-cta"
          style={{ minWidth: 220, marginTop: 18 }}
          disabled={busy}
          onClick={toggleRecord}
        >
          {recording ? '⏹ Stop and send' : '🎤 Speak your answer'}
        </button>

        {statusText && <p className="setup-hint" style={{ marginTop: 14 }}>{statusText}</p>}
        {busy && !recording && <p className="setup-hint" style={{ marginTop: 14 }}>…</p>}
      </div>
    </div>
  );
}
