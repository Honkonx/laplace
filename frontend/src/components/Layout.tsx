import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { ThemeToggle } from "./ThemeToggle";

type IconoId = "partidos" | "agente" | "historial" | "estado" | "seguimientos" | "simulador" | "cuenta";

const ICONOS: Record<IconoId, string> = {
  partidos: "M4 6h16M4 12h16M4 18h10",
  agente: "M5 6h14v9H9l-4 3V6z",
  historial: "M12 7v5l3 2M4 12a8 8 0 1 0 2.3-5.6M4 5v4h4",
  estado: "M3 12h4l3-7 4 14 3-7h4",
  seguimientos: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9L12 3z",
  simulador: "M5 19V9M12 19V5M19 19v-7",
  cuenta: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-7 8a7 7 0 0 1 14 0",
};

function Icono({ id }: { id: IconoId }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONOS[id]} />
    </svg>
  );
}

const SECCIONES: { to: string; etiqueta: string; icono: IconoId; end?: boolean }[] = [
  { to: "/", etiqueta: "Partidos", icono: "partidos", end: true },
  { to: "/agente", etiqueta: "Laplace", icono: "agente" },
  { to: "/historial", etiqueta: "Historial", icono: "historial" },
  { to: "/seguimientos", etiqueta: "Seguidos", icono: "seguimientos" },
  { to: "/estado", etiqueta: "Estado", icono: "estado" },
  { to: "/simulador", etiqueta: "Simulador", icono: "simulador" },
];

const enlaceEscritorio = ({ isActive }: { isActive: boolean }) =>
  `inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-medium transition-colors ${
    isActive ? "bg-surface-light text-text" : "text-text-muted hover:bg-surface-light hover:text-text"
  }`;

const enlaceMovil = ({ isActive }: { isActive: boolean }) =>
  `flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors ${
    isActive ? "text-accent" : "text-text-muted"
  }`;

export function Layout() {
  const { username, plan, rol, cerrarSesion } = useAuth();
  const planUpper = (plan ?? "free").toUpperCase();

  return (
    <div className="min-h-dvh bg-bg text-text">
      <header className="sticky top-0 z-20 border-b border-border bg-bg">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4">
          <Link to="/" className="flex items-center gap-2 text-text" aria-label="Laplace, ir al inicio">
            <img src="/icons/icon-192.png" alt="" width={32} height={32} className="h-8 w-8 rounded-lg" />
            <span className="text-lg font-semibold tracking-tight">Laplace</span>
          </Link>

          <nav className="hidden items-center gap-1 md:flex" aria-label="Principal">
            {SECCIONES.map((s) => (
              <NavLink key={s.to} to={s.to} end={s.end} className={enlaceEscritorio}>{s.etiqueta}</NavLink>
            ))}
            {rol === "admin" && <NavLink to="/admin" className={enlaceEscritorio}>Admin</NavLink>}
          </nav>

          <div className="flex items-center gap-1.5">
            <ThemeToggle />
            {rol === "admin" && <NavLink to="/admin" className={`${enlaceEscritorio({ isActive: false })} md:hidden`}>Admin</NavLink>}
            {username ? (
              <>
                <NavLink to="/entrar" className="btn btn-sm" title="Ver cuenta y activar código">
                  <span className="max-w-24 truncate">{username}</span>
                  <span className="rounded bg-surface-light px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                    {planUpper}
                  </span>
                </NavLink>
                <button type="button" onClick={() => void cerrarSesion()} className="btn btn-sm text-text-dim" title="Cerrar sesión">
                  Salir
                </button>
              </>
            ) : (
              <NavLink to="/entrar" className="btn btn-primary btn-sm">Entrar</NavLink>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 pb-24 pt-6 md:pb-10 md:pt-8">
        <Outlet />
      </main>

      <footer className="mx-auto hidden max-w-6xl px-4 pb-10 text-xs text-text-dim md:block">
        Laplace entrega estimaciones estadísticas de fútbol, no certezas ni consejos de apuestas. Cada pronóstico muestra de dónde sale su número.
      </footer>

      <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-bg pb-[env(safe-area-inset-bottom)] md:hidden" aria-label="Secciones">
        {SECCIONES.map((s) => (
          <NavLink key={s.to} to={s.to} end={s.end} className={enlaceMovil}>
            <Icono id={s.icono} />
            {s.etiqueta}
          </NavLink>
        ))}
        <NavLink to="/entrar" className={enlaceMovil}>
          <Icono id="cuenta" />
          {username ? planUpper : "Cuenta"}
        </NavLink>
      </nav>
    </div>
  );
}
