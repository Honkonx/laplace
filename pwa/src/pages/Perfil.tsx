import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { ApiError } from "@/lib/api";
import { canalTelegram, urlCanalTelegram } from "@/lib/comunidad";

// Perfil/Stats — a propósito NO muestra winrate/aciertos/fallos inventados: el contrato REST
// web (frontend/src/lib/api/, mismo que consume esta PWA) no expone un endpoint de
// estadísticas reales POR USUARIO — solo username/plan/device_id (`GET /api/v1/auth/me`). La
// app nativa (app-android/) sí muestra esos números porque los pide a la acción "stats" del
// webhook `x-kairos-key`, un contrato distinto que esta ronda tiene prohibido reusar sin
// revisar (no se expone `x-kairos-key` al browser — ver product-philosophy.md: mejor no
// mostrar un número que no se puede respaldar con datos reales, que mostrar uno inventado).
export function Perfil() {
  const { username, plan, activarCodigo, cerrarSesion, cargando } = useAuth();
  const [codigo, setCodigo] = useState("");
  const [mensaje, setMensaje] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!username) {
    return (
      <div className="flex flex-col items-center gap-4 pt-16 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent/15">
          <span className="text-2xl">👤</span>
        </div>
        <div>
          <h1 className="font-display text-xl font-bold">Todavía no entraste</h1>
          <p className="mt-1 text-sm text-text-muted">Creá una cuenta o entrá para ver tu perfil.</p>
        </div>
        <Link
          to="/entrar"
          className="w-full rounded-xl bg-accent py-3 text-center text-sm font-semibold text-white"
        >
          Entrar / Crear cuenta
        </Link>
      </div>
    );
  }

  async function canjear(e: FormEvent) {
    e.preventDefault();
    setMensaje(null);
    setError(null);
    try {
      const res = await activarCodigo(codigo.trim().toUpperCase());
      setMensaje(res.mensaje);
      setCodigo("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo activar el código.");
    }
  }

  const planUpper = (plan ?? "FREE").toUpperCase();
  const planColor = planUpper === "PRO" || planUpper === "MAX" ? "text-accent bg-accent/15" : "text-conf-media bg-conf-media/15";

  return (
    <div className="space-y-6 pt-1">
      <div className="flex flex-col items-center gap-2 pt-4">
        <div className="flex h-20 w-20 items-center justify-center rounded-full bg-accent/20">
          <span className="font-display text-2xl font-bold text-accent">{username.slice(0, 2).toUpperCase()}</span>
        </div>
        <h1 className="font-display text-xl font-bold">{username}</h1>
        <span className={`rounded-full px-3 py-1 text-xs font-bold ${planColor}`}>PLAN {planUpper}</span>
      </div>

      <form onSubmit={(e) => void canjear(e)} className="space-y-3 rounded-xl border border-border bg-surface p-4">
        <p className="text-sm font-medium">Canjear código de activación</p>
        <input
          value={codigo}
          onChange={(e) => setCodigo(e.target.value.toUpperCase())}
          placeholder="KS-PRO-XXXXXXX"
          minLength={6}
          maxLength={24}
          className="w-full rounded-xl border border-border bg-surface-light px-3 py-2.5 font-mono text-sm uppercase text-text outline-none focus:border-accent"
        />
        {mensaje && <p className="text-xs text-conf-alta">{mensaje}</p>}
        {error && <p className="text-xs text-conf-baja">{error}</p>}
        <button
          type="submit"
          disabled={cargando || codigo.trim().length < 6}
          className="w-full rounded-xl bg-accent py-2.5 text-xs font-semibold text-white disabled:opacity-50"
        >
          {cargando ? "Activando…" : "Activar código"}
        </button>
      </form>

      <div className="space-y-2">
        {canalTelegram() && (
          <a
            href={urlCanalTelegram()}
            target="_blank"
            rel="noreferrer"
            className="flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-3.5"
          >
            <div>
              <p className="text-sm font-medium">Comunidad Telegram</p>
              <p className="text-xs text-text-muted">@{canalTelegram()}</p>
            </div>
            <span className="text-text-dim">›</span>
          </a>
        )}
        <button
          onClick={() => void cerrarSesion()}
          className="w-full rounded-xl border border-border bg-surface px-4 py-3.5 text-left text-sm font-medium text-conf-baja"
        >
          Cerrar sesión
        </button>
      </div>

      <p className="text-center text-[11px] text-text-dim">
        Laplace es pronóstico deportivo — nunca casa de apuestas.
      </p>
    </div>
  );
}
