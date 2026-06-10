import { NavLink } from 'react-router-dom';
import { useAppStore } from '../../store/useAppStore';

const navItems = [
  { to: '/dashboard', label: 'Home', icon: 'H' },
  { to: '/profile', label: 'Profile', icon: 'P' },
  { to: '/create-resume', label: 'New', icon: '+' },
  { to: '/history', label: 'Runs', icon: 'R' },
  { to: '/settings', label: 'Settings', icon: 'S' },
];

export default function MobileNav() {
  const { generationId } = useAppStore();
  const items = generationId
    ? [
        { to: '/dashboard', label: 'Home', icon: 'H' },
        { to: '/profile', label: 'Profile', icon: 'P' },
        { to: '/create-resume', label: 'New', icon: '+' },
        { to: `/review/${generationId}`, label: 'Review', icon: 'E' },
        { to: '/history', label: 'Runs', icon: 'R' },
      ]
    : navItems;

  return (
    <nav className="mobile-bottom-nav" aria-label="Mobile navigation">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === '/dashboard'}
          aria-label={item.label}
          className={({ isActive }) => `mobile-nav-item ${isActive ? 'active' : ''}`}
        >
          <span className="mobile-nav-icon" aria-hidden="true">{item.icon}</span>
          <span className="mobile-nav-label">{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
