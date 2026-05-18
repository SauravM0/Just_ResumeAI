import type { ReactNode } from 'react';

type ErrorVariant = 'error' | 'unauthorized' | 'allowlist' | 'generation-failed' | 'expired';

interface Props {
  message: string;
  variant?: ErrorVariant;
  title?: string;
  onRetry?: () => void;
  action?: ReactNode;
}

const variantIcons: Record<ErrorVariant, string> = {
  'error': '!',
  'unauthorized': '\uD83D\uDD12',
  'allowlist': '\uD83D\uDEAB',
  'generation-failed': '\u26A0\uFE0F',
  'expired': '\u23F3',
};

const variantTitles: Record<ErrorVariant, string> = {
  'error': 'Something went wrong',
  'unauthorized': 'Session expired',
  'allowlist': 'Access restricted',
  'generation-failed': 'Resume generation failed',
  'expired': 'Files expired',
};

const variantDescriptions: Record<ErrorVariant, string> = {
  'error': '',
  'unauthorized': 'Your session has expired. Please sign in again to continue.',
  'allowlist': 'This workspace is not available for your account. Contact the administrator.',
  'generation-failed': '',
  'expired': 'Some exported files have expired. You can regenerate them from the generation detail page.',
};

export default function ErrorState({ message, variant = 'error', title, onRetry, action }: Props) {
  const icon = variantIcons[variant];
  const defaultTitle = variantTitles[variant];
  const defaultDescription = variantDescriptions[variant];

  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <div className="empty-title">{title || defaultTitle}</div>
      <div className="empty-description">{defaultDescription || message}</div>
      {message && defaultDescription && (
        <div className="empty-description" style={{ marginTop: 'var(--space-xs)', fontSize: '0.82rem' }}>
          {message}
        </div>
      )}
      {onRetry && (
        <div style={{ marginTop: 'var(--space-md)' }}>
          <button className="btn btn-primary" onClick={onRetry}>
            Try Again
          </button>
        </div>
      )}
      {action && (
        <div style={{ marginTop: 'var(--space-md)' }}>
          {action}
        </div>
      )}
    </div>
  );
}
