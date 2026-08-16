import { useState, useCallback, useEffect, useRef, startTransition } from 'react';
import SetupScreen from './components/SetupScreen';
import AuthModal from './components/AuthModal';
import LoadingScreen from './components/LoadingScreen';
import ChatScreen from './components/ChatScreen';
import RealtimeChatScreen from './components/RealtimeChatScreen';
import HistoryScreen from './components/HistoryScreen';
import ProgressScreen from './components/ProgressScreen';
import ToastStack from './components/ToastStack';
import {
  initChat, streamChat, regenerateTTS, getLanguages, getScenarios, getMe, logout as apiLogout,
} from './api';
import STATIC_LANGUAGES from './i18n/languages';
import { useT } from './i18n/useI18n';

const ENGLISH_ACCENT_VOICES = {
  american: 'iP95p4xoKVk53GoZ742B',
  british: 'pFZP5JQG7iQjIQuC4Bku',
  australian: 'IKne3meq5aSn9XLyUdCD',
};

const STATIC_TARGET_LANGUAGES = STATIC_LANGUAGES.map((l) => ({
  code: l.code,
  name: l.english,
  native_name: l.native,
}));

function normalizeLanguage(l) {
  return {
    code: l.code,
    name: l.name || l.english || l.code,
    native_name: l.native_name || l.native || l.name || l.code,
    // v11 M2: routes setup to RealtimeChatScreen instead of the cascade.
    realtime: !!l.realtime,
  };
}

function detectUiLang() {
  const stored = localStorage.getItem('lf_ui_lang');
  if (stored) return stored;
  const nav = (navigator.language || 'en').toLowerCase();
  const exact = STATIC_LANGUAGES.find((l) => nav === l.code);
  if (exact) return exact.code;
  const prefix = STATIC_LANGUAGES.find((l) => nav.startsWith(l.code));
  return prefix ? prefix.code : 'en';
}

export default function App() {
  const [screen, setScreen] = useState('setup');
  const [uiLang, setUiLang] = useState(detectUiLang);
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState(null); // null | 'login' | 'register'
  const [toasts, setToasts] = useState([]);

  // Onboarding selections
  // v12.1 (user-directed): the native language is ASSUMED to be the
  // interaction language — nativeLang tracks uiLang below unless the
  // learner picks a different one explicitly.
  const nativePickedRef = useRef(false);
  const [nativeLang, setNativeLang] = useState(null);
  const [targetLang, setTargetLang] = useState(null);
  // v12.1: default level so "Start learning" is enabled right after
  // choosing a language (the greyed-out CTA was a dead end).
  const [level, setLevel] = useState('beginner');
  const [accent, setAccent] = useState(() => localStorage.getItem('lf_accent') || 'american');
  const [scenario, setScenario] = useState(null); // null = free talk

  // Data
  const [languages, setLanguages] = useState(STATIC_TARGET_LANGUAGES);
  const [scenarios, setScenarios] = useState([]);

  // Chat session
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sending, setSending] = useState(false);
  const msgIdRef = useRef(1);
  const sendingRef = useRef(false);
  const toastSeqRef = useRef(1);
  const toastTimeoutRef = useRef([]);

  const nextMsgId = () => msgIdRef.current++;

  // ── Toasts ──
  const notify = useCallback((message, type = 'error') => {
    const id = toastSeqRef.current++;
    setToasts((prev) => [...prev, { id, message, type }]);
    const tid = setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4200);
    toastTimeoutRef.current.push(tid);
  }, []);

  // ── Boot: restore session, fetch languages + scenarios ──
  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((data) => { if (!cancelled && data?.user) setUser(data.user); })
      .catch((e) => { console.error('getMe failed:', e); if (!cancelled) notify('boot.error_get_me'); });
    getLanguages()
      .then((list) => { if (!cancelled && Array.isArray(list) && list.length) setLanguages(list.map(normalizeLanguage)); })
      .catch((e) => { console.error('getLanguages failed:', e); if (!cancelled) notify('boot.error_get_languages'); });
    getScenarios()
      .then((list) => { if (!cancelled && Array.isArray(list)) setScenarios(list); })
      .catch((e) => { console.error('getScenarios failed:', e); if (!cancelled) notify('boot.error_get_scenarios'); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    document.documentElement.lang = uiLang;
    localStorage.setItem('lf_ui_lang', uiLang);
    // Native language = interaction language, until manually overridden.
    if (nativePickedRef.current) return;
    const l = STATIC_LANGUAGES.find((x) => x.code === uiLang);
    if (l) setNativeLang({ code: l.code, name: l.english, native_name: l.native });
  }, [uiLang]);

  const handleNativeSelect = (l) => {
    nativePickedRef.current = true;
    setNativeLang(l);
  };

  // Persist accent preference across sessions
  useEffect(() => {
    localStorage.setItem('lf_accent', accent);
  }, [accent]);

  // ── Toast timeout cleanup ──
  useEffect(() => {
    return () => {
      toastTimeoutRef.current.forEach(clearTimeout);
      toastTimeoutRef.current = [];
    };
  }, []);

  // ── Chat lifecycle ──
  const startChat = useCallback(async ({ langObj, lvl, scenarioObj }) => {
    startTransition(() => {
      setTargetLang(langObj);
      setLevel(lvl);
      setScenario(scenarioObj || null);
      // Realtime-capable languages (v11 M2) go straight to the WS voice
      // screen — no initChat; the session starts on the first mic tap or
      // typed line. Everything else stays on the cascade engine below.
      setScreen(langObj.realtime ? 'realtime' : 'loading');
    });
    if (langObj.realtime) return;
    try {
      const voiceId = langObj.code === 'en' ? ENGLISH_ACCENT_VOICES[accent] : undefined;
      const res = await initChat({
        language: langObj.code,
        nativeLanguage: nativeLang?.code || 'en',
        level: lvl,
        scenarioId: scenarioObj?.id || '',
        voiceId,
      });
      setSessionId(res.session_id);
      const g = res.greeting || {};
      msgIdRef.current = 1;
      setMessages([{
        id: nextMsgId(),
        role: 'tutor',
        text: g.text || '',
        translation: g.translation || null,
        grammar: null,
        audio: g.audio_base64 || null,
        streaming: false,
      }]);
      setScreen('chat');
    } catch (e) {
      console.error('initChat failed:', e);
      notify('chat.error_init');
      setScreen('setup');
    }
  }, [accent, nativeLang, notify]);

  const sendChat = useCallback(async ({ blob, text }) => {
    if (!sessionId || !targetLang || sendingRef.current) return;
    sendingRef.current = true;
    setSending(true);

    const userId = nextMsgId();
    const tutorId = nextMsgId();
    const isTyped = typeof text === 'string';

    setMessages((prev) => [
      ...prev,
      { id: userId, role: 'user', text: isTyped ? text : '', pending: !isTyped, grammar: null },
      { id: tutorId, role: 'tutor', text: '', streaming: true },
    ]);

    let streamed = '';
    try {
      const res = await streamChat({
        sessionId,
        language: targetLang.code,
        audioBlob: blob,
        text: isTyped ? text : undefined,
        onToken: (tok) => {
          streamed += tok;
          const snapshot = streamed;
          setMessages((prev) => prev.map((m) => (m.id === tutorId ? { ...m, text: snapshot } : m)));
        },
        onAudio: (audioBase64) => {
          // Audio arrives on a separate SSE event after "complete" — attach it
          // to the tutor message; ChatScreen auto-plays when it lands.
          if (!audioBase64) return;
          setMessages((prev) => prev.map((m) => (m.id === tutorId ? { ...m, audio: audioBase64 } : m)));
        },
      });

      const reply = res.reply || {};
      const userText = res.user_text ?? (isTyped ? text : '');
      const errorType = res.error_type || null;

      setMessages((prev) => prev.map((m) => {
        if (m.id === userId) {
          return {
            ...m,
            text: userText,
            pending: false,
            noSpeech: !isTyped && userText === '',
            grammar: userText ? (reply.grammar || null) : null,
            error_type: errorType,
          };
        }
        if (m.id === tutorId) {
          return {
            id: tutorId,
            role: 'tutor',
            text: reply.text || streamed,
            translation: reply.translation || null,
            grammar: null,
            // "complete" never carries audio (skip_audio) — preserve whatever
            // the onAudio event attached earlier.
            audio: reply.audio_base64 || m.audio || null,
            streaming: false,
            error_type: errorType,
          };
        }
        return m;
      }));
    } catch (e) {
      console.error('sendChat failed:', e);
      // Keep any accumulated streamed text — don't nuke the tutor message.
      // Mark it as interrupted so the user sees what was received and can retry.
      setMessages((prev) => prev.map((m) => {
        if (m.id === tutorId && streamed) {
          return { ...m, text: streamed, streaming: false, interrupted: true };
        }
        // In voice mode, remove the pending user bubble (it was never sent).
        // In text mode, the user's own typed message stays visible.
        if (m.id === userId && !isTyped) return null;
        return m;
      }).filter(Boolean));
      notify('chat.error_send');
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }, [sessionId, targetLang, notify]);

  const handleSendAudio = useCallback((blob) => sendChat({ blob }), [sendChat]);
  const handleSendText = useCallback((text) => sendChat({ text }), [sendChat]);

  // ── Regenerate audio for a TTS-failed message ──
  const handleRegenerateAudio = useCallback(async (msgId, text) => {
    if (!sessionId || !targetLang) return;
    try {
      const data = await regenerateTTS({ sessionId, text, language: targetLang.code });
      setMessages((prev) => prev.map((m) =>
        m.id === msgId && data.audio_base64 ? { ...m, audio: data.audio_base64 } : m
      ));
    } catch (e) {
      console.error('TTS regen failed:', e);
      notify('chat.error_tts_regen', 'Audio generation failed');
    }
  }, [sessionId, targetLang, notify]);

  const endSession = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setScreen('setup');
  }, []);

  const newConversation = useCallback(() => {
    if (!targetLang || !level) return;
    // Clear current session, reset message counter, start fresh
    setMessages([]);
    setSessionId(null);
    msgIdRef.current = 1;
    startChat({ langObj: targetLang, lvl: level, scenarioObj: scenario });
  }, [targetLang, level, scenario, startChat]);

  // ── "Practice again" from history/progress — starts a FRESH session with
  // the same language/level/scenario (real conversation resume is a v9 TODO;
  // relabelled 2026-08-03 review finding 12).
  const handleResume = useCallback((summary) => {
    const langObj = languages.find((l) => l.code === summary.language)
      || { code: summary.language, name: summary.language, native_name: summary.language };
    const scenarioObj = scenarios.find((s) => s.id === summary.scenario_id) || null;
    startChat({ langObj, lvl: summary.level || 'intermediate', scenarioObj });
  }, [languages, scenarios, startChat]);

  // ── Auth ──
  const handleAuthSuccess = useCallback((u) => {
    setUser(u);
    setAuthMode(null);
  }, []);

  const handleLogout = useCallback(async () => {
    await apiLogout().catch(() => {});
    setUser(null);
  }, []);

  // ── Toast messages are i18n keys; translate at render time ──
  const t = useT(uiLang);

  return (
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column' }}>
      {screen === 'setup' && (
        <SetupScreen
          lang={uiLang}
          uiLang={uiLang}
          onUiLangChange={setUiLang}
          languages={languages}
          scenarios={scenarios}
          nativeLang={nativeLang}
          targetLang={targetLang}
          level={level}
          accent={accent}
          user={user}
          onLogin={() => setAuthMode('login')}
          onLogout={handleLogout}
          onProgress={() => setScreen('progress')}
          onNativeSelect={handleNativeSelect}
          onTargetSelect={(l) => {
            // SetupScreen's dropdown uses the static list — re-attach the
            // API's realtime flag by code (v11 M2 routing).
            const fromApi = languages.find((x) => x.code === l.code);
            setTargetLang({ code: l.code, name: l.english, native_name: l.native, realtime: !!fromApi?.realtime });
            setAccent('american');
          }}
          onLevelSelect={setLevel}
          onAccentChange={setAccent}
          onStart={({ langObj, lvl, scenarioObj }) => startChat({ langObj, lvl, scenarioObj })}
        />
      )}

      {screen === 'loading' && <LoadingScreen lang={uiLang} />}

      {screen === 'realtime' && targetLang && (
        <RealtimeChatScreen
          lang={uiLang}
          targetLang={targetLang}
          level={level}
          scenario={scenario}
          nativeLang={nativeLang}
          onEndSession={endSession}
          onLoginRequest={() => setAuthMode('register')}
        />
      )}

      {screen === 'chat' && (
        <ChatScreen
          lang={uiLang}
          targetLang={targetLang}
          level={level}
          scenario={scenario}
          messages={messages}
          sending={sending}
          onSendAudio={handleSendAudio}
          onSendText={handleSendText}
          onRegenerateAudio={handleRegenerateAudio}
          onEndSession={endSession}
          onNewConversation={newConversation}
          onNavigate={(s) => setScreen(s)}
          user={user}
        />
      )}

      {screen === 'history' && (
        <HistoryScreen
          lang={uiLang}
          user={user}
          languages={languages}
          scenarios={scenarios}
          onResume={handleResume}
          onBack={() => setScreen(sessionId ? 'chat' : 'setup')}
          onLoginRequest={() => setAuthMode('login')}
          notify={notify}
        />
      )}

      {screen === 'progress' && (
        <ProgressScreen
          lang={uiLang}
          user={user}
          languages={languages}
          onResume={handleResume}
          onBack={() => setScreen(sessionId ? 'chat' : 'setup')}
          onLoginRequest={() => setAuthMode('login')}
        />
      )}

      {authMode && (
        <AuthModal
          mode={authMode}
          lang={uiLang}
          onSuccess={handleAuthSuccess}
          onClose={() => setAuthMode(null)}
        />
      )}

      <ToastStack toasts={toasts.map((toast) => ({ ...toast, message: t(toast.message, toast.message) }))} />
    </div>
  );
}
