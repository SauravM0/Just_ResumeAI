import type { ReactNode } from 'react';

interface Props {
  label: string;
  id?: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
  className?: string;
}

/**
 * Reusable form field wrapper with label, hint, and error states.
 * Ensures consistent form styling across the app.
 */
export default function FormField({ label, id, hint, error, required, children, className = '' }: Props) {
  return (
    <div className={`form-group ${className}`}>
      <label className="form-label" htmlFor={id}>
        {label}
        {required && <span style={{ color: 'var(--text-danger)', marginLeft: 4 }}>*</span>}
      </label>
      {children}
      {error && (
        <span className="form-hint" style={{ color: 'var(--text-danger)' }}>
          {error}
        </span>
      )}
      {hint && !error && (
        <span className="form-hint">{hint}</span>
      )}
    </div>
  );
}
