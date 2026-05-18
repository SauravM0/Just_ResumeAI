import type { ReactNode } from 'react';

interface Props {
  icon?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}

export default function EmptyState({ icon, title, description, action }: Props) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-icon">{icon}</div>}
      <div className="empty-title">{title}</div>
      {description && <div className="empty-description">{description}</div>}
      {action && <div style={{ marginTop: 'var(--space-md)' }}>{action}</div>}
    </div>
  );
}
