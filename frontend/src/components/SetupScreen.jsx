import { useState } from 'react';
import { useT } from '../i18n/useI18n';
import LANGUAGES from '../i18n/languages';

const LEVELS = ['beginner', 'intermediate', 'fluent'];

// v13: the debate language dropdown (was: learning language). Pinned
// languages shown in a "Popular" optgroup: Mandarin, Cantonese, English.
// The native language has no dropdown — it is implicitly the interaction
// (UI) language (v12.1 design).
const POPULAR_LEARN = ['zh', 'yue', 'en'];

// v13: the learner profile — the personalization moat. Interests shape the
// coach's examples and subject suggestions; style shapes how hard it pushes.
const INTERESTS = ['tech', 'health', 'money', 'society', 'education', 'sports', 'politics', 'arts'];
const STYLES = ['devils_advocate', 'socratic', 'encouraging'];

function toggleIn(list, item) {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

/**
 * Single-page onboarding: debate language, depth — and optional subject and
 * profile — all on the first page. The CTA starts the debate via
 * onStart({langObj, lvl, scenarioObj, profile}) (the existing startChat).
 */
function LangOptions({ t, pinnedCodes }) {
  const pinned = pinnedCodes.map((c) => LANGUAGES.find((l) => l.code === c)).filter(Boolean);
  const rest = LANGUAGES.filter((l) => !pinnedCodes.includes(l.code));
  return (
    <>
      <optgroup label={t('setup.popular')}>
        {pinned.map((l) => (
          <option key={l.code} value={l.code}>{l.native} — {l.english}</option>
        ))}
      </optgroup>
      <optgroup label={t('setup.all')}>
        {rest.map((l) => (
          <option key={l.code} value={l.code}>{l.native} — {l.english}</option>
        ))}
      </optgroup>
    </>
  );
}

export default function SetupScreen({
  lang, uiLang, onUiLangChange, languages, scenarios,
  targetLang, level, profile, voices, voiceId, user,
  onLogin, onLogout, onProgress, onStart,
  onTargetSelect, onLevelSelect, onProfileChange, onVoiceSelect,
}) {
  const t = useT(lang);
  const [scenarioId, setScenarioId] = useState('');
  // Native language is optional — defaults to English in startChat (the old
  // wizard's "skip" behavior).
  const ready = targetLang && level;
  const interests = profile?.interests || [];
  const style = profile?.style || '';

  const begin = () => {
    if (!ready) return;
    const scenarioObj = scenarios.find((s) => s.id === scenarioId) || null;
    onStart({ langObj: targetLang, lvl: level, scenarioObj, profile });
  };

  return (
    <div className="screen setup-screen">
      {/* Header: UI language + auth (from WelcomeScreen) */}
      <nav className="welcome-nav">
        <span className="topbar-spacer" />
        {/* User-directed 2026-08-04: interface-language label → globe icon */}
        <label className="toggle-label ui-lang-icon" htmlFor="ui-lang-select" title={t('welcome.ui_language')}>
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="black" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="2" y1="12" x2="22" y2="12" />
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
          </svg>
        </label>
        <select
          id="ui-lang-select"
          className="select"
          aria-label={t('welcome.ui_language')}
          value={uiLang}
          onChange={(e) => onUiLangChange(e.target.value)}
        >
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>{l.native}</option>
          ))}
        </select>
        {user ? (
          <>
            <button className="btn btn-outline btn-sm" onClick={onProgress}>{t('welcome.progress')}</button>
            <button className="btn btn-ghost btn-sm" onClick={onLogout}>{t('welcome.logout')}</button>
          </>
        ) : (
          <button className="btn btn-outline btn-sm" onClick={onLogin}>{t('welcome.login')}</button>
        )}
      </nav>

      <div className="setup-body">
        {/* No native-language dropdown: it is implicitly the interaction
            (UI) language — the tutor explains in whatever language the
            interface runs in (v12.1 design, dropdown removed 2026-08-17). */}

        {/* Debate language — dropdown */}
        <section className="setup-section">
          <h2 className="setup-title">{t('lang.title')}</h2>
          <select
            className="select setup-native"
            value={targetLang?.code || ''}
            onChange={(e) => {
              const l = LANGUAGES.find((x) => x.code === e.target.value);
              if (l) onTargetSelect(l);
            }}
          >
            <option value="" disabled>{t('lang.select')}</option>
            <LangOptions t={t} pinnedCodes={POPULAR_LEARN} />
          </select>
        </section>

        {/* Debate depth */}
        <section className="setup-section">
          <h2 className="setup-title">{t('level.title')}</h2>
          <div className="setup-chips">
            {LEVELS.map((lvl) => (
              <button
                key={lvl}
                className={`setup-chip setup-chip-lg ${level === lvl ? 'setup-chip-active' : ''}`}
                onClick={() => onLevelSelect(lvl)}
              >
                {t('level.' + lvl)}
              </button>
            ))}
          </div>
        </section>

        {/* Coach voice (v13, user-directed 2026-08-18): pick from the
            options matching the session kind — realtime sessions can only
            use qwen presets, cascade sessions edge/elevenlabs voices.
            Hidden when only one option. */}
        {(() => {
          const usable = voices.filter((v) =>
            targetLang?.realtime ? v.provider === 'realtime' : v.provider !== 'realtime'
          );
          if (usable.length <= 1) return null;
          return (
            <section className="setup-section">
              <h2 className="setup-title">{t('voice.title')}</h2>
              <div className="setup-chips">
                {usable.map((v) => (
                  <button
                    key={v.voice_id}
                    className={`setup-chip ${voiceId === v.voice_id ? 'setup-chip-active' : ''}`}
                    onClick={() => onVoiceSelect(v.voice_id)}
                  >
                    {v.name}
                  </button>
                ))}
              </div>
            </section>
          );
        })()}

        {/* Optional subject — dropdown (10 options incl. free debate; >4 →
            dropdown per user-directed 2026-08-16 rule) */}
        {scenarios.length > 0 && (
          <section className="setup-section">
            <h2 className="setup-title">{t('scenario.pick_title')}</h2>
            <select
              className="select setup-native"
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
            >
              <option value="">{t('scenario.free_talk')}</option>
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>{s.title}</option>
              ))}
            </select>
          </section>
        )}

        {/* Learner profile — the personalization moat (v13). Never blocks
            the CTA; skip keeps whatever profile is already stored. */}
        <section className="setup-section">
          <h2 className="setup-title">{t('profile.title')}</h2>
          <p className="setup-hint">{t('profile.desc')}</p>

          <label className="field-label">{t('profile.interests')}</label>
          <div className="setup-chips">
            {INTERESTS.map((key) => (
              <button
                key={key}
                className={`setup-chip ${interests.includes(key) ? 'setup-chip-active' : ''}`}
                onClick={() =>
                  onProfileChange({ ...(profile || {}), interests: toggleIn(interests, key) })
                }
              >
                {t('profile.interest.' + key)}
              </button>
            ))}
          </div>

          <label className="field-label" style={{ marginTop: 14 }}>{t('profile.style')}</label>
          <div className="setup-chips">
            {STYLES.map((key) => (
              <button
                key={key}
                className={`setup-chip ${style === key ? 'setup-chip-active' : ''}`}
                onClick={() => onProfileChange({ ...(profile || {}), style: style === key ? '' : key })}
              >
                {t('profile.style.' + key)}
              </button>
            ))}
          </div>

          <button className="btn btn-ghost btn-sm setup-skip" onClick={() => onProfileChange({})}>
            {t('profile.skip')}
          </button>
        </section>

        <button className="btn btn-primary setup-cta" disabled={!ready} onClick={begin}>
          {t('welcome.cta')}
        </button>
      </div>
    </div>
  );
}
