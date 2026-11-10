import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { AdminStats } from "@/pages/admin/AdminStats";
import { AdminUsuarios } from "@/pages/admin/AdminUsuarios";
import { AdminCodigos } from "@/pages/admin/AdminCodigos";
import { AdminHistorialPlan } from "@/pages/admin/AdminHistorialPlan";
import { AdminIntentosLogin } from "@/pages/admin/AdminIntentosLogin";
import { AdminJobs } from "@/pages/admin/AdminJobs";
import { AdminIA } from "@/pages/admin/AdminIA";
import { AdminConexiones } from "@/pages/admin/AdminConexiones";

type Seccion = "stats" | "usuarios" | "codigos" | "historial" | "intentos" | "jobs" | "conexiones" | "ia";

const SECCIONES: { id: Seccion; etiqueta: string }[] = [
  { id: "stats", etiqueta: "Stats" },
  { id: "usuarios", etiqueta: "Usuarios" },
  { id: "codigos", etiqueta: "Códigos de acceso" },
  { id: "historial", etiqueta: "Historial de planes" },
  { id: "intentos", etiqueta: "Intentos de login" },
  { id: "jobs", etiqueta: "Jobs" },
  { id: "conexiones", etiqueta: "Conexiones" },
  { id: "ia", etiqueta: "IA global" },
];

// Panel de admin — solo lectura (v1, ver PROPUESTA_DASHBOARD_ADMIN.md).
// Guard: solo rol === "admin" pasa; cualquier otro rol (incluido null, sin sesión) vuelve
// a Home. AuthContext ya trae `rol` desde localStorage/login, no hace falta un fetch propio.
// 2026-09-10 — antes era `plan === "admin"` (pseudo-valor mezclado con el tier de suscripción,
// ver backend/api/models/usuarios.py §v7); el backend separó permiso (rol) de tier (plan).
export function Admin() {
  const { rol } = useAuth();
  const [seccion, setSeccion] = useState<Seccion>("stats");

  if (rol !== "admin") return <Navigate to="/" replace />;

  return (
    <div className="flex flex-col gap-6 md:flex-row">
      <aside className="flex shrink-0 gap-1 overflow-x-auto md:w-52 md:flex-col md:overflow-visible" aria-label="Secciones de administración">
        {SECCIONES.map((s) => (
          <button
            key={s.id}
            onClick={() => setSeccion(s.id)}
            aria-current={seccion === s.id ? "page" : undefined}
            className={`min-h-11 whitespace-nowrap rounded-lg px-3 text-left text-sm font-medium transition-colors ${
              seccion === s.id
                ? "bg-surface-light text-text"
                : "text-text-muted hover:bg-surface hover:text-text"
            }`}
          >
            {s.etiqueta}
          </button>
        ))}
      </aside>

      <div className="min-w-0 flex-1 space-y-6">
        <div>
          <h1 className="text-2xl">Administración</h1>
          <p className="mt-1 text-sm text-text-muted">
            Datos reales del backend, sin ejemplos.
          </p>
        </div>

        {seccion === "stats" && <AdminStats />}
        {seccion === "usuarios" && <AdminUsuarios />}
        {seccion === "codigos" && <AdminCodigos />}
        {seccion === "historial" && <AdminHistorialPlan />}
        {seccion === "intentos" && <AdminIntentosLogin />}
        {seccion === "jobs" && <AdminJobs />}
        {seccion === "conexiones" && <AdminConexiones />}
        {seccion === "ia" && <AdminIA />}
      </div>
    </div>
  );
}
