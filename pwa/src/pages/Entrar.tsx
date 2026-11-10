import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { ApiError } from "@/lib/api";

// Mismo patrón que frontend/src/pages/Entrar.tsx (usuario+clave, sin correo) — ver
// backend/api/routers/auth.py. Se navega acá desde Perfil cuando no hay sesión.
export function Entrar() {
  const [modo, setModo] = useState<"login" | "registro">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { iniciarSesion, registrarse, cargando } = useAuth();
  const navigate = useNavigate();

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (modo === "login") await iniciarSesion(username, password);
      else await registrarse(username, password);
      navigate("/perfil");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Algo salió mal. Probá de nuevo.");
    }
  }

  return (
    <div className="pt-1">
      <h1 className="mb-6 font-display text-2xl font-bold tracking-tight">
        {modo === "login" ? "Entrar" : "Crear cuenta"}
      </h1>

      <div className="mb-6 flex rounded-xl border border-border bg-surface p-1">
        <button
          onClick={() => setModo("login")}
          className={`flex-1 rounded-lg py-2.5 text-sm font-medium ${modo === "login" ? "bg-surface-light text-text" : "text-text-muted"}`}
        >
          Entrar
        </button>
        <button
          onClick={() => setModo("registro")}
          className={`flex-1 rounded-lg py-2.5 text-sm font-medium ${modo === "registro" ? "bg-surface-light text-text" : "text-text-muted"}`}
        >
          Crear cuenta
        </button>
      </div>

      <form onSubmit={(e) => void enviar(e)} className="space-y-4">
        <div>
          <label htmlFor="username" className="mb-1 block text-sm text-text-muted">Usuario</label>
          <input
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            minLength={3}
            maxLength={20}
            autoComplete="username"
            className="w-full rounded-xl border border-border bg-surface px-3 py-3 text-text outline-none focus:border-accent"
            placeholder="3 a 20 caracteres"
          />
        </div>
        <div>
          <label htmlFor="password" className="mb-1 block text-sm text-text-muted">Contraseña</label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete={modo === "login" ? "current-password" : "new-password"}
            className="w-full rounded-xl border border-border bg-surface px-3 py-3 text-text outline-none focus:border-accent"
            placeholder="Mínimo 8 caracteres"
          />
        </div>
        {error && <p className="text-sm text-conf-baja">{error}</p>}
        <button
          type="submit"
          disabled={cargando}
          className="w-full rounded-xl bg-accent py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          {cargando ? "Un momento…" : modo === "login" ? "Entrar" : "Crear cuenta"}
        </button>
      </form>
    </div>
  );
}
