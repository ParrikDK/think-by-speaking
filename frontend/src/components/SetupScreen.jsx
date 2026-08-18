import { useState } from 'react';
import { useT } from '../i18n/useI18n';
import LANGUAGES from '../i18n/languages';

const LEVELS = ['beginner', 'intermediate', 'fluent'];

// Pinned languages shown in a "Popular" optgroup at the top of the
// learning-language dropdown (user-directed 2026-08-03): Mandarin,
// Cantonese, English. The native language has no dropdown — it is
// implicitly the interaction (UI) language (v12.1 design).
const POPULAR_LEARN = ['zh', 'yue', 'en'];

const ENGLISH_ACCENTS = {
  american: '🇺🇸 American',
  british: '🇬🇧 British',
  australian: '🇦🇺 Australian',
};

/**
 * Single-page onboarding (spec §3.6): native language, learning language,
 * difficulty — and optional scenario — all on the first page. v8B visual
 * language (grid + chips + level pills). The CTA starts the chat via
 * onStart({langObj, lvl, scenarioObj}) (the existing startChat).
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
  targetLang, level, accent, user,
  onLogin, onLogout, onProgress, onStart,
  onTargetSelect, onLevelSelect, onAccentChange,
}) {
  const t = useT(lang);
  const [scenarioId, setScenarioId] = useState('');
  const isEnglish = targetLang?.code === 'en';
  // Native language is optional — defaults to English in startChat (the old
  // wizard's "skip" behavior).
  const ready = targetLang && level;

  const begin = () => {
    if (!ready) return;
    const scenarioObj = scenarios.find((s) => s.id === scenarioId) || null;
    onStart({ langObj: targetLang, lvl: level, scenarioObj });
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

        {/* Learning language — dropdown */}
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

        {/* Difficulty */}
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
          {isEnglish && (
            <div style={{ marginTop: 16 }}>
              <label className="field-label">{t('accent.label')}</label>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {Object.entries(ENGLISH_ACCENTS).map(([key, label]) => (
                  <button
                    key={key}
                    className={`setup-chip ${accent === key ? 'setup-chip-active' : ''}`}
                    onClick={() => onAccentChange(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </section>

        {/* Optional scenario — dropdown (10 options; >4 → dropdown per
            user-directed 2026-08-16 rule) */}
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

        <button className="btn btn-primary setup-cta" disabled={!ready} onClick={begin}>
          {t('welcome.cta')}
        </button>
      </div>
    </div>
  );
}
