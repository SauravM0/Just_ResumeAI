import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  sticky?: boolean;
}

export default function PrimaryActionBar({ children, sticky = true }: Props) {
  return (
    <div className={`primary-action-bar ${sticky ? 'primary-action-bar-sticky' : ''}`}>
      {children}
    </div>
  );
}
