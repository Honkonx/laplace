import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import * as api from "./api";

interface AuthState {
  username: string | null;
  plan: string | null;
  cargando: boolean;
  iniciarSesion: (u: string, p: string) => Promise<void>;
  registrarse: (u: string, p: string) => Promise<void>;
  activarCodigo: (codigo: string) => Promise<api.RespuestaActivarCodigo>;
  cerrarSesion: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

// localStorage para el JWT: mismo patrón que frontend/src/lib/AuthContext.tsx (SPA sin backend
// propio que pueda setear una cookie httpOnly). Claves prefijadas "laplace_" (frontend/ usa
// "laplace_web_") para que la PWA y la web de escritorio, si algún día corren en el mismo
// dominio/subdominio, no compartan ni pisen la sesión guardada de la otra por accidente.
export function AuthProvider({ children }: { children: ReactNode }) {
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem("laplace_username"));
  const [plan, setPlan] = useState<string | null>(() => localStorage.getItem("laplace_plan"));
  const [cargando, setCargando] = useState(false);

  const guardarSesion = (sesion: api.SesionUsuario) => {
    localStorage.setItem("laplace_token", sesion.token);
    localStorage.setItem("laplace_username", sesion.username);
    localStorage.setItem("laplace_plan", sesion.plan);
    setUsername(sesion.username);
    setPlan(sesion.plan);
  };

  const iniciarSesion = useCallback(async (u: string, p: string) => {
    setCargando(true);
    try {
      guardarSesion(await api.iniciarSesion(u, p));
    } finally {
      setCargando(false);
    }
  }, []);

  const registrarse = useCallback(async (u: string, p: string) => {
    setCargando(true);
    try {
      guardarSesion(await api.registrarse(u, p));
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
      // la sesión local — el usuario espera quedar desconectado en su celular.
    }
    localStorage.removeItem("laplace_token");
    localStorage.removeItem("laplace_username");
    localStorage.removeItem("laplace_plan");
    setUsername(null);
    setPlan(null);
  }, []);

  return (
    <AuthContext.Provider value={{ username, plan, cargando, iniciarSesion, registrarse, activarCodigo, cerrarSesion }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}
