import { useEffect, useState, useCallback } from 'react';
import { getHistory, getSessionMessages, deleteSession } from '../api';
import { useT } from '../i18n/useI18n';
import MessageBubble from './MessageBubble';

function formatDate(iso, lang) {
  try {
    return new Intl.DateTimeFormat(lang, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export default function HistoryScreen({ lang, user, languages, scenarios, onResume, onBack, onLoginRequest, notify }) {
  const t = useT(lang);
  const [sessions, setSessions] = useState(null); // null = loading
  const [error, setError] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [expandedMsgs, setExpandedMsgs] = useState([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [confirmId, setConfirmId] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const langLabel = useCallback((code) => {
    const l = languages.find((x) => x.code === code);
    return l ? (l.native_name || l.name) : code;
  }, [languages]);

  const scenarioLabel = useCallback((id) => {
    if (!id) return t('scenario.free_talk');
    const s = scenarios.find((x) => x.id === id);
    return s ? `${s.icon || '🎭'} ${s.title}` : id;
  }, [scenarios, t]);

  const load = useCallback(() => {
    setSessions(null);
    setError(false);
    getHistory()
      .then((list) => setSessions(Array.isArray(list) ? list : []))
      .catch(() => setError(true));
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  const toggleExpand = async (sessionId) => {
    if (expandedId === sessionId) {
      setExpandedId(null);
      setExpandedMsgs([]);
      return;
    }
    setExpandedId(sessionId);
    setExpandedMsgs([]);
    setLoadingMsgs(true);
    try {
      const data = await getSessionMessages(sessionId);
      // Pair grammar (carried on assistant replies) onto the preceding user message
      const raw = Array.isArray(data.messages) ? data.messages : [];
      const mapped = [];
      for (const m of raw) {
        const isUser = m.role === 'user';
        mapped.push({
          id: mapped.length + 1,
          role: isUser ? 'user' : 'tutor',
          text: m.text || '',
          translation: m.translation || null,
          grammar: isUser ? (m.grammar || null) : null,
          audio: null,
        });
        if (!isUser && m.grammar && mapped.length >= 2) {
          const prev = mapped[mapped.length - 2];
          if (prev.role === 'user' && !prev.grammar) {
            mapped[mapped.length - 2] = { ...prev, grammar: m.grammar };
          }
        }
      }
      setExpandedMsgs(mapped);
    } catch {
      notify('history.load_error', 'error');
      setExpandedId(null);
    } finally {
      setLoadingMsgs(false);
    }
  };

  const handleDelete = async (sessionId) => {
    if (confirmId !== sessionId) { setConfirmId(sessionId); return; }
    setDeleting(true);
    try {
      await deleteSession(sessionId);
      setSessions((prev) => prev.filter((s) => s.session_id !== sessionId));
      if (expandedId === sessionId) { setExpandedId(null); setExpandedMsgs([]); }
    } catch {
      notify('common.error', 'error');
    } finally {
      setDeleting(false);
      setConfirmId(null);
    }
  };

  if (!user) {
    return (
      <div className="screen">
        <div className="container">
          <button className="btn btn-ghost" onClick={onBack}>{t('common.back')}</button>
          <div className="empty-state">
            <div className="empty-state-icon">🔒</div>
            <p className="empty-state-sub">{t('history.login_prompt')}</p>
            <button className="btn btn-primary btn-sm" onClick={onLoginRequest}>{t('auth.login')}</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="screen">
      <div className="container container-wide">
        <button className="btn btn-ghost" onClick={onBack} style={{ marginBottom: 12 }}>{t('common.back')}</button>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'clamp(22px, 4vw, 30px)', fontWeight: 600, margin: '0 0 4px' }}>{t('history.title')}</h1>
        <p style={{ fontSize: 14, color: 'var(--color-ink-muted)', margin: '0 0 24px' }}>{t('history.sub')}</p>

        {error && (
          <div className="empty-state">
            <p className="empty-state-sub">{t('history.load_error')}</p>
            <button className="btn btn-outline btn-sm" onClick={load}>{t('common.retry')}</button>
          </div>
        )}

        {!error && sessions === null && (
          <div className="loading-wrap"><div className="spinner" /></div>
        )}

        {!error && sessions !== null && sessions.length === 0 && (
          <div className="empty-state">
            <div className="empty-state-icon">💬</div>
            <p className="empty-state-sub">{t('history.empty')}</p>
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {(sessions || []).map((s) => (
            <div key={s.session_id} className="card history-row">
              <div className="history-row-main">
                <span className="history-row-title">{langLabel(s.language)}</span>
                <span className="chip">{t('level.' + s.level, s.level)}</span>
                <span className="history-row-meta">{scenarioLabel(s.scenario_id)}</span>
                <span style={{ flex: 1 }} />
                <span className="history-row-meta">
                  {formatDate(s.last_active || s.started_at, lang)} · {s.message_count} {t('history.messages')}
                </span>
              </div>

              <div className="history-row-actions">
                <button className="btn btn-primary btn-sm" onClick={() => onResume(s)}>{t('history.resume')}</button>
                <button className="btn btn-outline btn-sm" onClick={() => toggleExpand(s.session_id)}>
                  {expandedId === s.session_id ? t('history.hide') : t('history.view')}
                </button>
                {confirmId === s.session_id ? (
                  <>
                    <button className="btn btn-sm" style={{ background: 'var(--color-pen)', color: '#fff' }} disabled={deleting} onClick={() => handleDelete(s.session_id)}>
                      {deleting ? t('common.loading') : t('history.confirm_delete')}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setConfirmId(null)}>{t('common.cancel')}</button>
                  </>
                ) : (
                  <button className="btn btn-ghost btn-sm" style={{ color: 'var(--color-pen)' }} onClick={() => handleDelete(s.session_id)}>
                    {t('history.delete')}
                  </button>
                )}
              </div>

              {expandedId === s.session_id && (
                <div className="history-messages">
                  {loadingMsgs && <div className="loading-wrap" style={{ padding: 16 }}><div className="spinner" /></div>}
                  {!loadingMsgs && expandedMsgs.map((m) => (
                    <MessageBubble key={m.id} msg={m} lang={lang} />
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
