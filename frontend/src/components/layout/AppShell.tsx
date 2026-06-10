import { useState, useEffect, type ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import UserMenu from '../UserMenu';

interface Props {
  children: ReactNode;
  title?: string;
}

const navItems = [
  { to: '/dashboard', label: 'Dashboard', icon: '📊' },
  { to: '/create-resume', label: 'New Resume', icon: '📄' },
  { to: '/history', label: 'History', icon: '🕐' },
  { to: '/profile', label: 'Profile', icon: '👤' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
];

export default function AppShell({ children, title }: Props) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  // Close sidebar on navigation (mobile)
  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  // Close sidebar on Escape key
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSidebarOpen(false);
    };
    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, []);

  const currentPageTitle = title || getPageTitle(location.pathname);

  return (
    <div className="app-layout">
      {/* Mobile sidebar overlay */}
      <div
        className={`sidebar-overlay ${sidebarOpen ? 'open' : ''}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />

      {/* Sidebar */}
      <aside className={`app-sidebar ${sidebarOpen ? 'sidebar-open' : ''}`} aria-label="Main navigation">
        <div className="sidebar-logo">
          <div className="logo-icon">JR</div>
          <h1>Just Resume</h1>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/dashboard'}
              className={({ isActive }) =>
                `nav-item ${isActive ? 'active' : ''}`
              }
              onClick={() => setSidebarOpen(false)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main frame */}
      <div className="app-main-frame">
        {/* Header */}
        <header className="app-header">
          <div className="app-header-left">
            <button
              className="mobile-menu-btn"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              aria-label={sidebarOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={sidebarOpen}
            >
              {sidebarOpen ? '✕' : '☰'}
            </button>
            <div>
              {location.pathname !== '/dashboard' && (
                <div className="app-header-eyebrow">Just Resume</div>
              )}
              <h2>{currentPageTitle}</h2>
            </div>
          </div>
          <UserMenu />
        </header>

        {/* Main content */}
        <main className="app-main-content">
          <div className="page-scroll">
            {children}
          </div>
        </main>

        {/* Mobile bottom nav */}
        <nav className="mobile-bottom-nav" aria-label="Mobile navigation">
          {navItems.slice(0, 5).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/dashboard'}
              className={({ isActive }) =>
                `mobile-nav-item ${isActive ? 'active' : ''}`
              }
              aria-label={item.label}
            >
              <span className="mobile-nav-icon" aria-hidden="true">
                {item.icon}
              </span>
              <span className="mobile-nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}

function getPageTitle(path: string): string {
  const titles: Record<string, string> = {
    '/dashboard': 'Dashboard',
    '/create-resume': 'New Resume',
    '/history': 'History',
    '/profile': 'Profile',
    '/settings': 'Settings',
    '/login': 'Sign In',
    '/access-denied': 'Access Denied',
  };

  // Check for review/:id routes
  if (path.startsWith('/review/')) return 'Resume Review';
  if (path.startsWith('/history/')) return 'History Detail';
  if (path.startsWith('/cover-letter')) return 'Cover Letter';

  return titles[path] || 'Just Resume';
}
