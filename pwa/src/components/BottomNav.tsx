import { NavLink } from "react-router-dom";
import { IconHome, IconCalendar, IconStar, IconChart, IconUser } from "./icons";

const DESTINOS = [
  { to: "/", label: "Inicio", Icon: IconHome, end: true },
  { to: "/calendario", label: "Calendario", Icon: IconCalendar, end: false },
  { to: "/picks", label: "Picks", Icon: IconStar, end: false },
  { to: "/simulador", label: "Simulador", Icon: IconChart, end: false },
  { to: "/agente", label: "Laplace", Icon: IconStar, end: false },
  { to: "/perfil", label: "Perfil", Icon: IconUser, end: false },
];

// Navegación tipo app — bottom nav fija de 5 destinos, espeja el patrón de app-android/ (mismo
// concepto que Mockup A de bocetos-kairos-v2.html, con Calendario y Simulador
// sumados a los 4 del mockup para cubrir las 5 pantallas que pide esta ronda). `env(safe-area-
// inset-bottom)` respeta el home indicator de iPhone en modo standalone (PWA instalada).
export function BottomNav() {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-surface/95 backdrop-blur"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      {DESTINOS.map(({ to, label, Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center gap-1 py-2.5 text-[10px] font-medium ${
              isActive ? "text-accent" : "text-text-dim"
            }`
          }
        >
          <Icon />
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
