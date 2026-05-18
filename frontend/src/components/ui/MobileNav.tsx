import { NavLink } from 'react-router-dom';
import { useAppStore } from '../../store/useAppStore';

const navItems = [
  { to: '/dashboard', label: 'Home', icon: '⌂' },
  { to: '/profile', label: 'Profile', icon: '👤' },
  { to: '/jd', label: 'New', icon: '📄' },
  { to: '/history', label: 'History', icon: '⏱' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
];

export default function MobileNav() {
  const { generationId } = useAppStore();
  const items = generationId
    ? [...navItems, { to: `/review/${generationId}`, label: 'Editor', icon: '✏️' }]
    : navItems;

  return (
    <nav className="mobile-bottom-nav">
      {items.slice(0, 6).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/dashboard'}
          className={({ isActive }) => `mobile-nav-item ${isActive ? 'active' : ''}`}
        >
          <span className="mobile-nav-icon">{item.icon}</span>
          <span className="mobile-nav-label">{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
