import { useEffect, useState, useCallback } from 'react';
import { getStats } from '../api';
import { aggregateGuestTurns } from '../utils/guestStats';
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

  // v13.1 guest memory: device-local analytics shown without an account
  const guestDebate = !user ? aggregateGuestTurns() : null;

  if (!user) {
    return (
      <div className="screen">
        <div className="container">
          <button className="btn btn-ghost" onClick={onBack} style={{ marginBottom: 12 }}>{t('common.back')}</button>
          <h1 style={{ fontFamily: 'var(--font-display)', fontSize: 'clamp(22px, 4vw, 30px)', fontWeight: 600, margin: '0 0 4px' }}>{t('progress.title')}</h1>
          <p style={{ fontSize: 14, color: 'var(--color-ink-muted)', margin: '0 0 24px' }}>{t('progress.sub')}</p>

          <div className="card" style={{ padding: 18, marginBottom: 16 }}>
            <p style={{ fontSize: 14, margin: 0 }}>📱 {t('progress.device_memory')}</p>
          </div>

          {guestDebate ? (
            <DebateAnalytics d={guestDebate} t={t} />
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">🌱</div>
              <p className="empty-state-sub">{t('progress.empty')}</p>
            </div>
          )}

          <div className="empty-state" style={{ marginTop: 8 }}>
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
                    <BarRow key={code} label={langLabel(code)} value={v?.sessions || 0} max={maxSessions} />
                  ))}
                </div>
              </section>
            )}

            {(() => {
              const d = stats?.debate || {};
              if (!d.turns) return null;
              return <DebateAnalytics d={d} t={t} />;
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

// Shared debate-analytics section (logged-in server data or guest device
// memory — same shape, same look).
// Debate analytics per the dataviz method (2026-08-19): score history as
// single-hue sequential bars (height = magnitude, selective labels,
// per-mark tooltips, hairline baseline, 2px gaps, 4px rounded data-ends),
// fallacy breakdown as labeled chips tinted with validated categorical
// slots in FIXED order (identity never color-alone), plus a table view.
function DebateAnalytics({ d, t }) {
  const history = Array.isArray(d.score_history) ? d.score_history : [];
  const fallacies = Object.entries(d.fallacy_totals || {}).sort(([a], [b]) => (a < b ? -1 : 1));
  const maxScore = Math.max(100, ...history.map((h) => h.avg_score || 0));
  const bestIdx = history.reduce((bi, h, i) => (h.avg_score > (history[bi]?.avg_score || 0) ? i : bi), 0);
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
          <div className="da-chart" role="img" aria-label={t('progress.score_history')}>
            {history.map((h, i) => (
              <div key={h.session_id} className="da-bar" style={{ height: `${Math.max(6, Math.round(((h.avg_score || 0) / maxScore) * 100))}%` }}>
                <div className="da-tip">
                  {t('progress.avg_score')}: {h.avg_score} · {h.turns} {t('progress.turns')}
                  <br />{h.started_at ? h.started_at.slice(0, 10) : ''}
                </div>
                {/* selective labels: only the best session and the latest */}
                {i === bestIdx && <span className="da-label da-label-best">{h.avg_score}</span>}
                {i === history.length - 1 && i !== bestIdx && <span className="da-label">{h.avg_score}</span>}
              </div>
            ))}
          </div>
          <details className="da-table">
            <summary>{t('progress.table_view')}</summary>
            <table>
              <thead>
                <tr><th>{t('progress.date')}</th><th>{t('progress.avg_score')}</th><th>{t('progress.turns')}</th><th>{t('progress.best_score')}</th></tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.session_id}>
                    <td>{h.started_at ? h.started_at.slice(0, 10) : ''}</td>
                    <td>{h.avg_score}</td>
                    <td>{h.turns}</td>
                    <td>{h.best}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </div>
      )}

      {fallacies.length > 0 && (
        <div className="da-chips">
          {fallacies.map(([type, n], i) => (
            <FallacyChip key={type} type={type} count={n} t={t} slot={i + 1} />
          ))}
        </div>
      )}
    </section>
  );
}

// Shared bar row (by-language + score history) and fallacy chip (also
// used by DebateCard) — extracted during the /simplify pass.
export function BarRow({ label, value, max, suffix }) {
  return (
    <div className="bar-row">
      <span className="bar-name">{label}</span>
      <span className="bar-track">
        <span className="bar-fill" style={{ width: `${Math.round(((value || 0) / max) * 100)}%` }} />
      </span>
      <span className="bar-count">{value} {suffix}</span>
    </div>
  );
}

export function FallacyChip({ type, count, t, slot }) {
  const label = t('debate.fallacy.' + type, type.replace(/_/g, ' '));
  // Fixed categorical slot (validated palette order) — identity is carried
  // by the label; the hue only reinforces it.
  return (
    <span className="debate-fallacy da-fallacy-chip" style={{ '--chip': `var(--cat-${slot})` }} title={label}>
      {label}{count != null ? ` ×${count}` : ''}
    </span>
  );
}
