// Debate Tutor - v13 API client, implements docs/api-contract.md
const API_BASE = '/api';

const TOKEN_KEY = 'lf_token';
const USER_KEY = 'lf_username';

// ── Auth storage ─────────────────────────────────

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser() {
  const username = localStorage.getItem(USER_KEY);
  return username ? { username } : null;
}

export function isLoggedIn() {
  return !!getToken();
}

function storeAuth(data) {
  localStorage.setItem(TOKEN_KEY, data.token);
  localStorage.setItem(USER_KEY, data.user?.username || '');
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function errorDetail(res, fallback) {
  try {
    const err = await res.json();
    if (err && typeof err.detail === 'string') return err.detail;
  } catch { /* non-JSON error body */ }
  return fallback;
}

// ── Meta ─────────────────────────────────────────

/** GET JSON with auth headers (unless overridden) — throws errorDetail on failure. */
async function getJSON(path, { fallback, headers = authHeaders() } = {}) {
  const res = await fetch(`${API_BASE}${path}`, { headers });
  if (!res.ok) throw new Error(await errorDetail(res, `${fallback} (${res.status})`));
  return res.json();
}

export async function getHealth() {
  return getJSON('/health', { fallback: 'Health check failed', headers: {} });
}

export async function getLanguages() {
  return getJSON('/languages', { fallback: 'Languages fetch failed' }); // [{code, name, native_name, tts}]
}

export async function getScenarios(language) {
  const q = language ? `?language=${encodeURIComponent(language)}` : '';
  return getJSON(`/scenarios${q}`, { fallback: 'Scenarios fetch failed' }); // [{id, title, description, icon}]
}

export async function getVoices(language) {
  const q = language ? `?language=${encodeURIComponent(language)}` : '';
  return getJSON(`/voices${q}`, { fallback: 'Voices fetch failed' }); // [{voice_id, name, provider}]
}

// ── Auth ─────────────────────────────────────────

export async function register(username, password) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const e = new Error(await errorDetail(res, 'Registration failed'));
    e.status = res.status;
    throw e;
  }
  const data = await res.json();
  storeAuth(data);
  return data; // {token, user}
}

export async function login(username, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const e = new Error(await errorDetail(res, 'Login failed'));
    e.status = res.status;
    throw e;
  }
  const data = await res.json();
  storeAuth(data);
  return data; // {token, user}
}

export async function logout() {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: authHeaders(),
    });
  } finally {
    clearAuth();
  }
}

export async function getMe() {
  if (!getToken()) return null;
  const res = await fetch(`${API_BASE}/auth/me`, { headers: authHeaders() });
  if (res.status === 401) {
    clearAuth(); // token expired or invalid
    return null;
  }
  if (!res.ok) return null;
  return res.json(); // {user, stats}
}

// ── Realtime voice (v11 M2) ──────────────────────

/**
 * Build the WebSocket URL for /api/realtime/ws. Browser WebSockets can't
 * set headers, so the auth token rides as a query param (bad/absent token =
 * guest trial on the server). `cont` marks a session-cap rollover
 * reconnect (server skips the greeting).
 */
export function realtimeWsUrl({ lang, level, mode, scenarioId, native, cont, profile, voice }) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const params = new URLSearchParams({ lang, level, mode });
  if (scenarioId) params.set('scenario_id', scenarioId);
  if (native) params.set('native', native);
  if (profile && Object.keys(profile).length > 0) {
    params.set('profile', JSON.stringify(profile)); // URLSearchParams encodes
  }
  if (voice) params.set('voice', voice);
  const token = getToken();
  if (token) params.set('token', token);
  if (cont) params.set('cont', '1');
  return `${proto}://${window.location.host}${API_BASE}/realtime/ws?${params.toString()}`;
}

// ── Chat ─────────────────────────────────────────

export async function initChat({ language, nativeLanguage, level, scenarioId, voiceId, profile }) {
  const form = new FormData();
  form.append('language', language);
  form.append('native_language', nativeLanguage || 'en');
  form.append('level', level || 'beginner');
  form.append('scenario_id', scenarioId || ''); // empty string = free talk
  if (voiceId) form.append('voice_id', voiceId);
  if (profile && Object.keys(profile).length > 0) {
    form.append('profile', JSON.stringify(profile));
  }

  const res = await fetch(`${API_BASE}/chat/init`, {
    method: 'POST',
    headers: authHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(await errorDetail(res, `Init failed (${res.status})`));
  return res.json(); // {session_id, greeting: TurnPayload}
}

/**
 * Send one chat turn to the streaming endpoint.
 * Pass EITHER audioBlob (webm/opus) OR text (typed input).
 * onToken(text) fires for each streamed reply token; onAudio(base64) fires
 * when the TTS audio arrives (after `complete`); resolves with the `complete`
 * payload: {session_id, user_text, reply: TurnPayload}.
 */
const SSE_TIMEOUT_MS = 60000; // generous: server heartbeats keep it alive

const SSE_MAX_RETRIES = 2;
const SSE_RETRY_DELAY_MS = 1000;

export async function streamChat({ sessionId, language, audioBlob, text, onToken, onAudio }) {
  const form = new FormData();
  form.append('session_id', sessionId);
  form.append('language', language);
  // Name the file by its real type — iOS records mp4 (not webm); Scribe
  // sniffs the extension/content-type, so a mismatched name risks rejection.
  const audioName = audioBlob?.type.startsWith('audio/mp4') ? 'recording.m4a' : 'recording.webm';
  if (audioBlob) form.append('audio', audioBlob, audioName);
  else form.append('text', text ?? '');

  let lastError;
  for (let attempt = 0; attempt <= SSE_MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      console.warn(`streamChat: reconnecting (attempt ${attempt}/${SSE_MAX_RETRIES})`);
      await new Promise((r) => setTimeout(r, SSE_RETRY_DELAY_MS));
    }

    const ac = new AbortController();
    let timeoutId = setTimeout(() => ac.abort(), SSE_TIMEOUT_MS);

    let res;
    try {
      res = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: authHeaders(),
        body: form,
        signal: ac.signal,
      });
    } catch (e) {
      clearTimeout(timeoutId);
      if (e.name === 'AbortError') {
        if (attempt < SSE_MAX_RETRIES) { lastError = e; continue; }
        throw new Error('Request timed out — no response from server');
      }
      throw e;
    }
    if (!res.ok) { clearTimeout(timeoutId); throw new Error(await errorDetail(res, `Chat failed (${res.status}`)); }
    if (!res.body) { clearTimeout(timeoutId); throw new Error('No response stream'); }

    const resetTimeout = () => {
      clearTimeout(timeoutId);
      if (ac.signal.aborted) return;
      timeoutId = setTimeout(() => ac.abort(), SSE_TIMEOUT_MS);
    };

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let complete = null;

    const dispatch = (event, data) => {
      if (event === 'token') {
        try {
          const d = JSON.parse(data);
          if (d.text && onToken) onToken(d.text);
        } catch { /* ignore malformed token frame */ }
      } else if (event === 'complete') {
        complete = JSON.parse(data);
      } else if (event === 'audio') {
        try {
          const d = JSON.parse(data);
          if (onAudio) onAudio(d.audio_base64 || '');
        } catch { /* ignore malformed audio frame */ }
      } else if (event === 'error') {
        let msg = 'Stream error';
        try { msg = JSON.parse(data).detail || msg; } catch { /* keep default */ }
        throw new Error(msg);
      }
      // 'done' and unknown events need no handling
    };

    // SSE framing: events separated by blank lines; lines are `event:` / `data:`.
    const drain = (final = false) => {
      let idx;
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        let event = 'message';
        const dataLines = [];
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
        }
        if (dataLines.length) dispatch(event, dataLines.join('\n'));
      }
      if (final && buffer.trim()) {
        // Tolerate a trailing event with no final blank line
        buffer += '\n\n';
        drain(false);
      }
    };

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        resetTimeout();
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
        drain();
      }
    } catch (e) {
      clearTimeout(timeoutId);
      if (e.name === 'AbortError') {
        // The turn was already delivered ("complete" fired) — the abort is
        // only the TTS/audio phase timing out. NEVER re-POST: that would
        // duplicate the turn server-side (STT + LLM + persistence). The
        // audio is best-effort; resolve with what we have.
        if (complete) return complete;
        if (attempt < SSE_MAX_RETRIES) { lastError = e; continue; }
        throw new Error(`Stream timed out (no data for ${SSE_TIMEOUT_MS / 1000}s)`);
      }
      throw e;
    }
    clearTimeout(timeoutId);
    buffer += decoder.decode().replace(/\r\n/g, '\n');
    drain(true);

    if (!complete) throw new Error('Stream ended without a complete event');
    return complete;
  }
  throw lastError || new Error('Stream failed after retries');
}

// ── History / Stats (Bearer required) ────────────

export async function getHistory() {
  return getJSON('/history', { fallback: 'History fetch failed' }); // [{session_id, language, level, scenario_id, started_at, last_active, message_count}]
}

export async function getSessionMessages(sessionId) {
  return getJSON(`/history/${encodeURIComponent(sessionId)}`, { fallback: 'Session fetch failed' }); // {session, messages}
}

export async function deleteSession(sessionId) {
  const res = await fetch(`${API_BASE}/history/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(await errorDetail(res, `Delete failed (${res.status})`));
  return res.json(); // {ok: true}
}

export async function getStats() {
  return getJSON('/stats', { fallback: 'Stats fetch failed' }); // {total_sessions, total_messages, total_minutes, by_language, recent_sessions, streak_days}
}

export async function regenerateTTS({ sessionId, text, language }) {
  const body = new FormData();
  body.append('session_id', sessionId);
  body.append('text', text);
  body.append('language', language);
  const res = await fetch(`${API_BASE}/chat/tts`, {
    method: 'POST',
    headers: authHeaders(),
    body,
  });
  if (!res.ok) throw new Error(await errorDetail(res, `TTS regen failed (${res.status})`));
  return res.json(); // {audio_base64: "..."}
}
