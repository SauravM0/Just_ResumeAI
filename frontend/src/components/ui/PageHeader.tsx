import type { ReactNode } from 'react';

interface Props {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  badge?: ReactNode;
}

export default function PageHeader({ title, subtitle, actions, badge }: Props) {
  return (
    <div className="page-header app-page-header">
      <div className="page-header-content">
        <div className="page-header-text">
          <h1 className="page-title">{title}</h1>
          {subtitle && <p className="page-subtitle">{subtitle}</p>}
        </div>
        {badge && <div className="page-header-badge">{badge}</div>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  );
}
