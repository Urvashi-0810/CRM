import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

function initials(name) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0].toUpperCase())
    .join('')
}

export default function Layout() {
  const { me, logout } = useAuth()
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">SG</span>
          <span>
            <strong>Shield Global</strong>
            <small>Demand Letter CRM</small>
          </span>
        </div>
        <nav aria-label="Main">
          <p className="nav-section">Core modules</p>
          <NavLink to="/demands" className="nav-link">
            Demand Drafts
          </NavLink>
          <NavLink to="/advertisements" className="nav-link">
            Create Advertisement
          </NavLink>
          <NavLink to="/profile" className="nav-link">
            My Profile
          </NavLink>
          <NavLink to="/admin" className="nav-link">
            Admin
          </NavLink>
        </nav>
        <div className="sidebar-user">
          <span className="avatar" aria-hidden="true">{initials(me.display_name)}</span>
          <span className="sidebar-user-text">
            <strong>{me.display_name}</strong>
            <small>{me.role || 'No role set'}</small>
          </span>
          <button className="link-btn" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
