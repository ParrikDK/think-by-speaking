export default function ToastStack({ toasts }) {
  if (!toasts.length) return null;
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className={toast.type === 'error' ? 'toast toast-error' : 'toast'}>
          {toast.message}
        </div>
      ))}
    </div>
  );
}
