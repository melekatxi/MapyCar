import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "../auth/AuthContext";

const NAV_ITEMS = [
  { to: "/mapa", label: "Mapa" },
  { to: "/zonas", label: "Zonas" },
  { to: "/planificacion", label: "Planificación" },
  { to: "/optimizacion", label: "Optimizador" },
  { to: "/historico", label: "Histórico" },
  { to: "/campo", label: "Campo" },
  { to: "/compartir", label: "Compartir" },
  { to: "/importar", label: "Importar" },
  { to: "/geocodificacion", label: "Geocodificación" },
];

export function ProtectedLayout() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-brand">Sofia</span>
        <button
          type="button"
          className="nav-toggle"
          aria-expanded={menuOpen}
          aria-controls="app-nav"
          onClick={() => setMenuOpen((open) => !open)}
        >
          Menú
        </button>
      </header>
      <nav
        id="app-nav"
        className={`app-nav ${menuOpen ? "app-nav--open" : ""}`}
      >
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `app-nav__link ${isActive ? "app-nav__link--active" : ""}`
            }
            onClick={() => setMenuOpen(false)}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <main className="app-content">
        <Outlet />
      </main>
    </div>
  );
}
