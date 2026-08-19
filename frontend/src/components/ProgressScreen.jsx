import { useEffect, useState, useCallback } from 'react';
import { getStats } from '../api';
import { useT } from '../i18n/useI18n';

export default function ProgressScreen({ lang, user, languages, onResume, onBack, onLoginRequest }) {
  const t = useT(lang);
  const [stats, setStats] = useState(null); // null = loading
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    setStats(null);
    setError(false);
    getStats()
      .then(setStats)
      .catch(() => setError(true));
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  const langLabel = useCallback((code) => {
    const l = languages.find((x) => x.code === code);
    return l ? (l.name || l.native_name) : code;
  }, [languages]);

  if (!user) {
    return (
      <div className="screen">
        <div className="container">
          <button className="btn btn-ghost" onClick={onBack}>{t('common.back')}</button>
          <div className="empty-state">
            <div className="empty-state-icon">🔒</div>
            <p className="empty-state-sub">{t('progress.login_prompt')}</p>
            <button className="btn btn-primary btn-sm" onClick={onLoginRequest}>{t('auth.login')}</button>
          </div>
        </div>
      </div>
    );
  }

  const byLanguage = stats?.by_language || {};
  const langEntries = Object.entries(byLanguage).sort((a, b) => (b[1]?.sessions || 0) - (a[1]?.sessions || 0));
  const maxSessions = Math.max(1, ...langEntries.map(([, v]) => v?.sessions || 0));
  const recent = stats?.recent_sessions || [];
  const isEmpty = stats && !stats.total_sessions;

  return (
    <div className="screen">
      <div className="container container-wide">
        <button className="btn btn-ghost" onClick={onBack} style={{ marginBottom: 12 }}>{t('common.back')}</button>
        <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'clamp(22px, 4vw, 30px)', fontWeight: 600, margin: '0 0 4px' }}>{t('progress.title')}</h1>
        <p style={{ fontSize: 14, color: 'var(--color-ink-muted)', margin: '0 0 24px' }}>{t('progress.sub')}</p>

        {error && (
          <div className="empty-state">
            <p className="empty-state-sub">{t('progress.load_error')}</p>
            <button className="btn btn-outline btn-sm" onClick={load}>{t('common.retry')}</button>
          </div>
        )}

        {!error && stats === null && (
          <div className="loading-wrap"><div className="spinner" /></div>
        )}

        {!error && isEmpty && (
          <div className="empty-state">
            <div className="empty-state-icon">🌱</div>
            <p className="empty-state-sub">{t('progress.empty')}</p>
          </div>
        )}

        {!error && stats && !isEmpty && (
          <>
            <div className="stat-grid">
              <div className="card stat-card">
                <div className="stat-value">{stats.total_sessions ?? 0}</div>
                <div className="stat-label">{t('progress.sessions')}</div>
              </div>
              <div className="card stat-card">
                <div className="stat-value">{stats.total_messages ?? 0}</div>
                <div className="stat-label">{t('progress.messages')}</div>
              </div>
              <div className="card stat-card">
                <div className="stat-value">{Math.round(stats.total_minutes ?? 0)}</div>
                <div className="stat-label">{t('progress.minutes')}</div>
              </div>
              <div className="card stat-card">
                <div className="stat-value">🔥 {stats.streak_days ?? 0}</div>
                <div className="stat-label">{t('progress.streak')}</div>
              </div>
            </div>

            {langEntries.length > 0 && (
              <section style={{ marginBottom: 28 }}>
                <h2 className="section-title">{t('progress.by_language')}</h2>
                <div className="card" style={{ padding: 18 }}>
                  {langEntries.map(([code, v]) => (
                    <div key={code} className="bar-row">
                      <span className="bar-name">{langLabel(code)}</span>
                      <span className="bar-track">
                        <span className="bar-fill" style={{ width: `${Math.round(((v?.sessions || 0) / maxSessions) * 100)}%` }} />
                      </span>
                      <span className="bar-count">{v?.sessions || 0}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Debate analytics — persistent
                progress that is the moat. */}
            {(() => {
              const d = stats?.debate || {};
              const history = Array.isArray(d.score_history) ? d.score_history : [];
              const fallacies = Object.entries(d.fallacy_totals || {});
              const maxScore = Math.max(100, ...history.map((h) => h.avg_score || 0));
              if (!d.turns) return null;
              return (
                <section style={{ marginBottom: 28 }}>
                  <h2 className="section-title">{t('progress.debate_analytics')}</h2>
                  <div className="stat-grid">
                    <div className="card stat-card">
                      <div className="stat-value">{d.avg_score ?? 0}</div>
                      <div className="stat-label">{t('progress.avg_score')}</div>
                    </div>
                    <div className="card stat-card">
                      <div className="stat-value">{d.best_score ?? 0}</div>
                      <div className="stat-label">{t('progress.best_score')}</div>
                    </div>
                    <div className="card stat-card">
                      <div className="stat-value">{d.sessions ?? 0}</div>
                      <div className="stat-label">{t('progress.debates')}</div>
                    </div>
                    <div className="card stat-card">
                      <div className="stat-value">{d.filler_total ?? 0}</div>
                      <div className="stat-label">{t('progress.fillers')}</div>
                    </div>
                  </div>

                  {history.length > 0 && (
                    <div className="card" style={{ padding: 18, marginTop: 14 }}>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {history.map((h) => (
                          <div key={h.session_id} className="bar-row">
                            <span className="bar-name">{h.avg_score}</span>
                            <span className="bar-track">
                              <span className="bar-fill" style={{ width: `${Math.round(((h.avg_score || 0) / maxScore) * 100)}%` }} />
                            </span>
                            <span className="bar-count">{h.turns} {t('progress.turns')}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {fallacies.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
                      {fallacies.map(([type, n]) => (
                        <span key={type} className="debate-fallacy" title={t('debate.fallacy.' + type, type)}>
                          ⚠️ {t('debate.fallacy.' + type, type.replace(/_/g, ' '))} ×{n}
                        </span>
                      ))}
                    </div>
                  )}
                </section>
              );
            })()}

            {recent.length > 0 && (
              <section>
                <h2 className="section-title">{t('progress.recent')}</h2>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {recent.map((s) => (
                    <div key={s.session_id} className="card history-row">
                      <div className="history-row-main">
                        <span className="history-row-title">{langLabel(s.language)}</span>
                        <span className="chip">{t('level.' + s.level, s.level)}</span>
                        <span style={{ flex: 1 }} />
                        <span className="history-row-meta">{s.message_count} {t('history.messages')}</span>
                      </div>
                      <div className="history-row-actions">
                        <button className="btn btn-outline btn-sm" onClick={() => onResume(s)}>{t('history.resume')}</button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
