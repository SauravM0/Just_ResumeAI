import { lazy, Suspense, useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ProtectedRoute, { AuthLoadingScreen } from './components/ProtectedRoute';
import UserMenu from './components/UserMenu';
import MobileNav from './components/ui/MobileNav';
import { useAppStore } from './store/useAppStore';
import { useAuthStore } from './store/useAuthStore';
import './index.css';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const MasterProfile = lazy(() => import('./pages/MasterProfile'));
const JDInput = lazy(() => import('./pages/JDInput'));
const ResumeReview = lazy(() => import('./pages/ResumeReview'));
const CoverLetter = lazy(() => import('./pages/CoverLetter'));
const History = lazy(() => import('./pages/History'));
const HistoryDetail = lazy(() => import('./pages/HistoryDetail'));
const Settings = lazy(() => import('./pages/Settings'));
const Login = lazy(() => import('./pages/Login'));
const AccessDenied = lazy(() => import('./pages/AccessDenied'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
    mutations: { retry: 0 },
  },
});

const navItems = [
  { path: '/dashboard', label: 'Dashboard', icon: '⌂' },
  { path: '/profile', label: 'Master Profile', icon: '👤' },
  { path: '/jd', label: 'New Resume', icon: '📄' },
  { path: '/history', label: 'History', icon: '⏱' },
  { path: '/settings', label: 'Settings', icon: '⚙' },
];

const pageTitles: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/profile': 'Master Profile',
  '/jd': 'New Resume',
  '/history': 'History',
  '/settings': 'Settings',
};

function RootRedirect() {
  const { session, loading, initialized } = useAuthStore();
  if (loading || !initialized) {
    return <AuthLoadingScreen />;
  }
  return <Navigate to={session ? '/dashboard' : '/login'} replace />;
}

function AppLayout() {
  const location = useLocation();
  const { generationId } = useAppStore();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const currentTitle = generationId && location.pathname.startsWith('/review')
    ? 'Resume Editor'
    : generationId && location.pathname.startsWith('/cover-letter')
    ? 'Cover Letter'
    : generationId && location.pathname.startsWith('/history/')
    ? 'Generation Detail'
    : pageTitles[location.pathname] || 'JustResume AI';

  const workflowItems = [
    {
      path: generationId ? `/review/${generationId}` : '#',
      label: 'Resume Editor',
      disabled: !generationId,
    },
    {
      path: generationId ? `/cover-letter/${generationId}` : '#',
      label: 'Cover Letter',
      disabled: !generationId,
    },
  ];

  return (
    <div className="app-layout">
      <div
        className={`sidebar-overlay ${sidebarOpen ? 'open' : ''}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />

      <aside className={`sidebar app-sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-logo">
          <div className="logo-icon">JR</div>
          <h1>JustResume AI</h1>
        </div>

        <nav className="sidebar-nav" aria-label="Primary navigation">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/dashboard'}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              onClick={() => setSidebarOpen(false)}
            >
              <span className="nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="workflow-nav">
          <div className="section-label">Current run</div>
          {workflowItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `nav-item nav-item-compact ${isActive ? 'active' : ''} ${item.disabled ? 'disabled' : ''}`
              }
              onClick={(event) => {
                if (item.disabled) event.preventDefault();
                else setSidebarOpen(false);
              }}
            >
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>

        <div className="session-panel">
          <div className="section-label">Generation</div>
          {generationId ? (
            <div className="session-pill session-pill-active">{generationId.slice(0, 8)}...</div>
          ) : (
            <div className="session-pill">No active generation</div>
          )}
        </div>
      </aside>

      <div className="app-main-frame">
        <header className="app-header">
          <div className="app-header-left">
            <button
              className="mobile-menu-btn"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              aria-label="Toggle navigation menu"
            >
              {sidebarOpen ? '✕' : '☰'}
            </button>
            <div>
              <p className="app-header-eyebrow">JustResume</p>
              <h2>{currentTitle}</h2>
            </div>
          </div>
          <UserMenu />
        </header>

        <main className="main-content app-main-content">
          <div className="page-scroll">
            <PageSuspense>
              <Routes>
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/profile" element={<MasterProfile />} />
                <Route path="/jd" element={<JDInput />} />
                <Route path="/review/:generationId" element={<ResumeReview />} />
                <Route path="/review" element={<Navigate to={generationId ? `/review/${generationId}` : '/jd'} replace />} />
                <Route path="/history" element={<History />} />
                <Route path="/history/:generationId" element={<HistoryDetail />} />
                <Route path="/cover-letter/:generationId" element={<CoverLetter />} />
                <Route path="/cover-letter" element={<Navigate to={generationId ? `/cover-letter/${generationId}` : '/jd'} replace />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
              </Routes>
            </PageSuspense>
          </div>
        </main>

        <MobileNav />
      </div>
    </div>
  );
}

function PageSuspense({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="page-scroll" style={{ padding: 'var(--space-lg)' }}><div className="spinner spinner-lg" style={{ margin: '0 auto' }} /></div>}>
      {children}
    </Suspense>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/login" element={<PageSuspense><Login /></PageSuspense>} />
      <Route path="/access-denied" element={<PageSuspense><AccessDenied /></PageSuspense>} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      />
    </Routes>
  );
}

export default function App() {
  const initialize = useAuthStore((state) => state.initialize);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
