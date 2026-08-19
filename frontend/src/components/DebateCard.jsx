import { useT } from '../i18n/useI18n';

/**
 * Post-turn debate feedback card (v13). Attached to USER messages: the
 * coach's stance on the claim, the running debate score with delta, the
 * counter-argument, one evidence-backed fact, the next challenge — plus
 * the RhetoricX pillars (v13.1): fallacy radar chips, structure line and
 * the filler count.
 *
 * @param {object} feedback - {stance, score, score_delta, counter, evidence,
 *                            next, fallacies, structure, filler_count}
 * @param {string} lang     - UI language code
 */
export default function DebateCard({ feedback, lang }) {
  const t = useT(lang);
  if (!feedback) return null;

  const { stance, score, score_delta, counter, evidence, next, fallacies, structure, filler_count } = feedback;
  const delta = Number(score_delta) || 0;
  const deltaClass = delta > 0 ? 'debate-delta-up' : delta < 0 ? 'debate-delta-down' : 'debate-delta-flat';
  const deltaArrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '±';
  const fallaciesList = Array.isArray(fallacies) ? fallacies.filter((f) => f && f.type) : [];
  const fillers = Number(filler_count) || 0;

  return (
    <div className="debate-card">
      <div className="debate-card-head">
        <div className="debate-score">
          <span className="debate-score-num">{Number(score) || 50}</span>
          <span className={`debate-delta ${deltaClass}`}>
            {deltaArrow} {delta !== 0 ? Math.abs(delta) : '0'}
          </span>
        </div>
        <span className={`debate-stance debate-stance-${stance}`}>
          {t('debate.stance.' + stance, stance)}
        </span>
      </div>

      {/* Fallacy radar (RhetoricX pillar) */}
      {fallaciesList.length > 0 && (
        <div className="debate-row">
          <span className="debate-label">{t('debate.fallacies', 'Fallacies')}</span>
          <div className="debate-fallacies">
            {fallaciesList.map((f, i) => (
              <span
                key={i}
                className="debate-fallacy"
                title={f.quote ? `${f.quote} — ${f.note || ''}` : (f.note || '')}
              >
                ⚠️ {t('debate.fallacy.' + f.type, f.type.replace(/_/g, ' '))}
                {f.note ? <span className="debate-fallacy-note"> {f.note}</span> : null}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Delivery chips: fillers + structure */}
      {(fillers > 0 || structure) && (
        <div className="debate-row">
          <span className="debate-label">{t('debate.delivery', 'Delivery')}</span>
          <div className="debate-fallacies">
            {fillers > 0 && (
              <span className="debate-fallacy debate-fallacy-delivery">
                🎙️ {fillers} {t('debate.fillers', 'fillers')}
              </span>
            )}
            {structure && <span className="debate-fallacy debate-fallacy-delivery">{structure}</span>}
          </div>
        </div>
      )}

      {counter && (
        <div className="debate-row">
          <span className="debate-label">{t('debate.counter', "Coach's rebuttal")}</span>
          <span className="debate-text">{counter}</span>
        </div>
      )}
      {evidence && (
        <div className="debate-row">
          <span className="debate-label">{t('debate.evidence', 'The evidence')}</span>
          <span className="debate-text">{evidence}</span>
        </div>
      )}
      {next && (
        <div className="debate-row debate-row-next">
          <span className="debate-label">{t('debate.next', 'Your challenge')}</span>
          <span className="debate-text">{next}</span>
        </div>
      )}
    </div>
  );
}
