import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/useAuthStore';

function userInitial(email?: string): string {
  return email?.trim().charAt(0).toUpperCase() || 'U';
}

export default function UserMenu() {
  const { user, signOut, loading } = useAuthStore();
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const email = user?.email ?? '';
  const name = user?.user_metadata?.full_name || user?.user_metadata?.name || email;

  return (
    <div className="user-menu">
      <button
        type="button"
        className="user-menu-trigger"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label="Open user menu"
      >
        <span className="user-avatar">{userInitial(email)}</span>
        <span className="user-menu-copy">
          <span className="user-name">{name || 'Signed in'}</span>
          <span className="user-email">{email}</span>
        </span>
      </button>

      {open && (
        <div className="user-menu-popover">
          <div className="user-menu-details">
            <strong>{name || 'JustResume user'}</strong>
            <span>{email}</span>
          </div>
          <button
            type="button"
            className="btn btn-ghost user-menu-action"
            onClick={() => { navigate('/settings'); setOpen(false); }}
          >
            Settings
          </button>
          <hr className="user-menu-divider" />
          <button
            type="button"
            className="btn btn-secondary user-menu-action"
            onClick={() => void signOut()}
            disabled={loading}
          >
            {loading ? 'Signing out...' : 'Log out'}
          </button>
        </div>
      )}
    </div>
  );
}
