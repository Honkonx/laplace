import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import * as api from "./api";

interface AuthState {
  username: string | null;
  plan: string | null;
  // rol — 2026-09-10, separado de plan (ver backend/api/models/usuarios.py §v7).
  rol: string | null;
  cargando: boolean;
  iniciarSesion: (u: string, p: string) => Promise<void>;
  registrarse: (u: string, p: string, termsAccepted: boolean) => Promise<void>;
  activarCodigo: (codigo: string) => Promise<api.RespuestaActivarCodigo>;
  cerrarSesion: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

// localStorage para el JWT: es el patrón estándar de una SPA sin backend propio (no hay
// servidor que setee una cookie httpOnly acá) — más simple, pero un XSS real podría robar el
// token. Aceptable para este alcance; si en el futuro esto necesita más seguridad, la opción
// real es agregar un backend-for-frontend que sí pueda setear cookies httpOnly.
// Claves prefijadas "laplace_" (no "laplace_" a secas, mismo prefijo que pwa/src/lib/
// AuthContext.tsx) para que esta web de escritorio y la PWA, si algún día corren en el mismo
// dominio/subdominio, no compartan ni pisen la sesión guardada de la otra por accidente.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem("laplace_username"));
  const [plan, setPlan] = useState<string | null>(() => localStorage.getItem("laplace_plan"));
  const [rol, setRol] = useState<string | null>(() => localStorage.getItem("laplace_rol"));
  const [cargando, setCargando] = useState(false);

  const guardarSesion = (sesion: api.SesionUsuario) => {
    localStorage.setItem("laplace_token", sesion.token);
    localStorage.setItem("laplace_username", sesion.username);
    localStorage.setItem("laplace_plan", sesion.plan);
    localStorage.setItem("laplace_rol", sesion.rol);
    setUsername(sesion.username);
    setPlan(sesion.plan);
    setRol(sesion.rol);
  };

  const iniciarSesion = useCallback(async (u: string, p: string) => {
    setCargando(true);
    try {
      guardarSesion(await api.iniciarSesion(u, p));
    } finally {
      setCargando(false);
    }
  }, []);

  const registrarse = useCallback(async (u: string, p: string, termsAccepted: boolean) => {
    setCargando(true);
    try {
      guardarSesion(await api.registrarse(u, p, termsAccepted));
    } finally {
      setCargando(false);
    }
  }, []);

  const activarCodigo = useCallback(async (codigo: string) => {
    setCargando(true);
    try {
      const res = await api.activarCodigoWeb(codigo);
      if (res.token) localStorage.setItem("laplace_token", res.token);
      localStorage.setItem("laplace_plan", res.plan);
      if (res.rol) {
        localStorage.setItem("laplace_rol", res.rol);
        setRol(res.rol);
      }
      setPlan(res.plan);
      return res;
    } finally {
      setCargando(false);
    }
  }, []);

  const cerrarSesion = useCallback(async () => {
    try {
      await api.cerrarSesion();
    } catch {
      // si el logout contra el backend falla (token ya vencido, red caída) igual limpiamos
      // la sesión local — el usuario espera quedar desconectado en su navegador.
    }
    localStorage.removeItem("laplace_token");
    localStorage.removeItem("laplace_username");
    localStorage.removeItem("laplace_plan");
    localStorage.removeItem("laplace_rol");
    setUsername(null);
    setPlan(null);
    setRol(null);
  }, []);

  return (
    <AuthContext.Provider value={{ username, plan, rol, cargando, iniciarSesion, registrarse, activarCodigo, cerrarSesion }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}
