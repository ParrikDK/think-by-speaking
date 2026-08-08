import { useState } from 'react';
import { useT } from '../i18n/useI18n';
import { login, register } from '../api';

export default function AuthModal({ mode: initialMode = 'login', lang, onSuccess, onClose }) {
  const t = useT(lang);
  const [mode, setMode] = useState(initialMode);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const isLogin = mode === 'login';

  const submit = async (e) => {
    e.preventDefault();
    if (busy || !username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      const fn = isLogin ? login : register;
      const data = await fn(username.trim(), password);
      onSuccess(data.user);
    } catch (err) {
      if (err.status === 401) setError(t('auth.error_creds'));
      else if (err.status === 409) setError(t('auth.error_taken'));
      else setError(err.message && err.message !== 'Login failed' && err.message !== 'Registration failed'
        ? err.message
        : t('auth.error_generic'));
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h2 className="modal-title">{isLogin ? t('auth.login_title') : t('auth.register_title')}</h2>
        <p className="modal-sub">{isLogin ? t('auth.login_sub') : t('auth.register_sub')}</p>

        {error && <div className="modal-error">{error}</div>}

        <form onSubmit={submit}>
          <div className="field">
            <label className="field-label" htmlFor="auth-username">{t('auth.username')}</label>
            <input
              id="auth-username"
              className="input"
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="auth-password">{t('auth.password')}</label>
            <input
              id="auth-password"
              className="input"
              type="password"
              autoComplete={isLogin ? 'current-password' : 'new-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button className="btn btn-primary" type="submit" disabled={busy || !username.trim() || !password} style={{ width: '100%' }}>
            {busy ? t('common.loading') : isLogin ? t('auth.login') : t('auth.register')}
          </button>
        </form>

        <p className="modal-switch">
          <button className="btn btn-ghost" onClick={() => { setMode(isLogin ? 'register' : 'login'); setError(null); }}>
            {isLogin ? t('auth.switch_to_register') : t('auth.switch_to_login')}
          </button>
        </p>
        <p className="modal-guest">
          <button className="btn btn-ghost" onClick={onClose}>{t('auth.guest')}</button>
        </p>
      </div>
    </div>
  );
}
