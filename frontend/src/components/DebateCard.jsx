import { useT } from '../i18n/useI18n';

/**
 * Post-turn debate feedback card (v13). Attached to USER messages: the
 * coach's stance on the claim, the running debate score with delta, the
 * counter-argument, one evidence-backed fact, and the next challenge.
 *
 * @param {object} feedback - {stance, score, score_delta, counter, evidence, next}
 * @param {string} lang     - UI language code
 */
export default function DebateCard({ feedback, lang }) {
  const t = useT(lang);
  if (!feedback) return null;

  const { stance, score, score_delta, counter, evidence, next } = feedback;
  const delta = Number(score_delta) || 0;
  const deltaClass = delta > 0 ? 'debate-delta-up' : delta < 0 ? 'debate-delta-down' : 'debate-delta-flat';
  const deltaArrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '±';

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
