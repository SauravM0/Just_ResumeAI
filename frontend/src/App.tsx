/**
 * App root — layout shell with sidebar navigation + page routing.
 */

import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Dashboard from './pages/Dashboard';
import MasterProfile from './pages/MasterProfile';
import JDInput from './pages/JDInput';
import ResumeReview from './pages/ResumeReview';
import LatexEditor from './pages/LatexEditor';
import CoverLetter from './pages/CoverLetter';
import { useAppStore } from './store/useAppStore';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
    mutations: { retry: 0 },
  },
});

function AppLayout() {
  const { sessionId } = useAppStore();

  const navItems = [
    { path: '/', icon: '🏠', label: 'Dashboard' },
    { path: '/profile', icon: '👤', label: 'Master Profile' },
    { path: '/jd', icon: '📋', label: 'Job Description' },
    { path: '/review', icon: '👁️', label: 'Resume Review', requiresSession: true },
    { path: '/editor', icon: '📑', label: 'LaTeX Editor', requiresSession: true },
    { path: '/cover-letter', icon: '✉️', label: 'Cover Letter', requiresSession: true },
  ];

  return (
    <div className="app-layout">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-icon">JR</div>
          <h1>JustResume AI</h1>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => {
            const disabled = item.requiresSession && !sessionId;
            return (
              <NavLink
                key={item.path}
                to={disabled ? '#' : item.path}
                className={({ isActive }) =>
                  `nav-item ${isActive ? 'active' : ''} ${disabled ? 'disabled' : ''}`
                }
                onClick={(e) => disabled && e.preventDefault()}
                style={disabled ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
              >
                <span className="nav-icon">{item.icon}</span>
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        {/* Session indicator */}
        <div style={{
          borderTop: '1px solid var(--border-subtle)',
          paddingTop: 'var(--space-md)',
          marginTop: 'auto',
        }}>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Session
          </div>
          {sessionId ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--status-success)' }} />
              <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
                {sessionId.slice(0, 8)}...
              </span>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--text-tertiary)' }} />
              <span style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)' }}>No active session</span>
            </div>
          )}
        </div>
      </aside>

      {/* Main Content */}
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/profile" element={<MasterProfile />} />
          <Route path="/jd" element={<JDInput />} />
          <Route path="/review" element={<ResumeReview />} />
          <Route path="/editor" element={<LatexEditor />} />
          <Route path="/cover-letter" element={<CoverLetter />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppLayout />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
