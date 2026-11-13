import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { describirError } from "@/lib/errores";

type Modo = "login" | "registro";

export function Entrar() {
  const [modo, setModo] = useState<Modo>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [terminos, setTerminos] = useState(false);
  const [codigo, setCodigo] = useState("");
  const [mensajeCodigo, setMensajeCodigo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { username: usuarioActivo, plan, iniciarSesion, registrarse, activarCodigo, cerrarSesion, cargando } = useAuth();
  const navigate = useNavigate();

  async function canjearCodigo(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMensajeCodigo(null);
    try {
      const res = await activarCodigo(codigo.trim().toUpperCase());
      setMensajeCodigo(res.mensaje);
      setCodigo("");
    } catch (err) {
      const amigable = describirError(err);
      setError(amigable.tipo === "red" ? `${amigable.titulo}. ${amigable.detalle}` : amigable.detalle);
    }
  }

  if (usuarioActivo) {
    const planActual = (plan ?? "free").toUpperCase();
    return (
      <div className="mx-auto max-w-md space-y-6 pt-2 md:pt-8">
        <div className="rounded-xl border border-border bg-surface p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-xs text-text-muted">Cuenta activa</p>
              <h1 className="text-xl font-semibold">{usuarioActivo}</h1>
            </div>
            <span className="rounded-full bg-surface-light px-3 py-1 text-xs font-semibold text-accent">
              PLAN {planActual}
            </span>
          </div>
          <p className="mt-3 text-xs text-text-muted">
            Para usar este mismo plan en Telegram, envía{" "}
            <code className="rounded bg-surface-light px-1.5 py-0.5 text-text">/vincular {usuarioActivo} &lt;tu_clave&gt;</code>{" "}
            al bot.
          </p>
        </div>

        <form onSubmit={(e) => void canjearCodigo(e)} className="space-y-3 rounded-xl border border-border bg-surface p-5">
          <h2 className="text-base font-semibold">Canjear código de activación</h2>
          <p className="text-xs text-text-muted">
            Ingresa tu código <code className="text-text">KS-PRO-XXXXXXX</code> o <code className="text-text">KS-MAX-XXXXXXX</code> para actualizar tu plan al instante.
          </p>
          <div>
            <label htmlFor="codigo-acceso" className="mb-1 block text-xs font-medium text-text-muted">Código</label>
            <input
              id="codigo-acceso"
              value={codigo}
              onChange={(e) => setCodigo(e.target.value.toUpperCase())}
              required
              minLength={6}
              maxLength={24}
              placeholder="KS-PRO-XXXXXXX"
              className="field font-mono uppercase"
            />
          </div>
          {mensajeCodigo && (
            <p role="status" className="rounded-lg border border-conf-alta/50 p-3 text-sm text-conf-alta">
              {mensajeCodigo}
            </p>
          )}
          {error && (
            <p role="alert" className="rounded-lg border border-conf-baja/50 p-3 text-sm text-conf-baja">
              {error}
            </p>
          )}
          <button type="submit" disabled={cargando || codigo.trim().length < 6} className="btn btn-primary w-full">
            {cargando ? "Activando…" : "Activar código"}
          </button>
        </form>

        <button type="button" onClick={() => void cerrarSesion()} className="btn w-full">
          Cerrar sesión
        </button>
      </div>
    );
  }

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (modo === "login") await iniciarSesion(username, password);
      else {
        if (!terminos) { setError("Para crear una cuenta debes aceptar los Términos y Condiciones."); return; }
        await registrarse(username, password, terminos);
      }
      navigate("/");
    } catch (err) {
      const amigable = describirError(err);
      setError(amigable.tipo === "red" ? `${amigable.titulo}. ${amigable.detalle}` : amigable.detalle);
    }
  }

  const pestana = (id: Modo, etiqueta: string) => (
    <button type="button" role="tab" id={`tab-${id}`} aria-selected={modo === id} aria-controls="panel-entrar" onClick={() => { setModo(id); setError(null); }}
      className={`min-h-11 flex-1 rounded-md text-sm font-medium transition-colors ${modo === id ? "bg-surface-light text-text" : "text-text-muted hover:text-text"}`}>
      {etiqueta}
    </button>
  );

  return (
    <div className="mx-auto max-w-sm pt-2 md:pt-8">
      <h1 className="text-xl">{modo === "login" ? "Entra a Laplace" : "Crea tu cuenta"}</h1>
      <p className="mt-1 text-sm text-text-muted">Con tu cuenta puedes pedir pronósticos, guardar tu historial y conversar con el asistente.</p>

      <div role="tablist" aria-label="Acceso" className="mt-5 flex gap-1 rounded-lg border border-border bg-surface p-1">
        {pestana("login", "Entrar")}
        {pestana("registro", "Crear cuenta")}
      </div>

      <form id="panel-entrar" role="tabpanel" aria-labelledby={`tab-${modo}`} onSubmit={(e) => void enviar(e)} className="mt-5 space-y-4">
        <div>
          <label htmlFor="username" className="mb-1 block text-sm font-medium">Usuario</label>
          <input id="username" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} maxLength={20} autoComplete="username" className="field" placeholder="3 a 20 caracteres" />
        </div>
        <div>
          <label htmlFor="password" className="mb-1 block text-sm font-medium">Contraseña</label>
          <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} autoComplete={modo === "login" ? "current-password" : "new-password"} className="field" placeholder="Mínimo 8 caracteres" />
        </div>
        {modo === "registro" && (
          <label className="flex items-start gap-3 rounded-lg border border-border bg-surface p-3 text-xs leading-5 text-text-muted">
            <input type="checkbox" checked={terminos} onChange={(e) => setTerminos(e.target.checked)} className="mt-1 h-4 w-4 shrink-0 accent-[var(--t-accent)]" />
            <span>
              Acepto los <strong className="text-text">Términos y Condiciones</strong>. Laplace usa y es creado con IA; guarda mis conversaciones y preferencias para operar memoria y mejorar mi experiencia. Es una herramienta de análisis y pronóstico deportivo, no de apuestas ni asesoría financiera. Soy responsable de mis decisiones y de cualquier pérdida de capital.
            </span>
          </label>
        )}
        {error && <p role="alert" className="rounded-lg border border-conf-baja/50 p-3 text-sm text-conf-baja">{error}</p>}
        <button type="submit" disabled={cargando} className="btn btn-primary w-full">
          {cargando ? "Un momento…" : modo === "login" ? "Entrar" : "Crear cuenta"}
        </button>
      </form>
    </div>
  );
}
