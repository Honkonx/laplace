import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { obtenerHistorialWeb, obtenerPrecisionUsuario, type PrecisionUsuario } from "@/lib/api";
import { describirError } from "@/lib/errores";
import { useAuth } from "@/lib/AuthContext";
import { ConfianzaBadge } from "@/components/ConfianzaBadge";

type Items = Awaited<ReturnType<typeof obtenerHistorialWeb>>["items"];

function fechaLarga(fecha: string): string {
  const d = new Date(/^\d{8}$/.test(fecha) ? `${fecha.slice(0, 4)}-${fecha.slice(4, 6)}-${fecha.slice(6)}T12:00:00` : fecha);
  return Number.isNaN(d.getTime()) ? fecha : d.toLocaleDateString("es-CL", { weekday: "short", day: "numeric", month: "short" });
}

export function Historial() {
  const { username } = useAuth();
  const [items, setItems] = useState<Items | null>(null);
  const [precision, setPrecision] = useState<PrecisionUsuario | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!username) return;
    obtenerHistorialWeb().then((d) => setItems(d.items)).catch((e: unknown) => setError(describirError(e).detalle));
    obtenerPrecisionUsuario().then(setPrecision).catch(() => setPrecision(null));
  }, [username]);

  if (!username) {
    return (
      <section className="panel mx-auto max-w-lg p-6">
        <h1 className="text-xl">Tu historial</h1>
        <p className="mt-2 text-sm text-text-muted">Entra para guardar y volver a consultar los pronósticos que pediste.</p>
        <Link to="/entrar" className="btn btn-primary mt-4">Entrar</Link>
      </section>
    );
  }

  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-2xl">Historial de pronósticos</h1>
        <p className="mt-1 text-sm text-text-muted">Los pronósticos que pediste, guardados solo en tu cuenta.</p>
      </div>
      {precision && precision.picks_consultados > 0 && (
        <div className="panel p-3 text-sm" aria-label="Tu acierto">
          <p><span className="text-text-muted">Tu acierto: </span>
            {precision.acierto_pct == null ? "sin partidos terminados todavía" : <strong className="num">{precision.aciertos} de {precision.verificados} ({precision.acierto_pct}%)</strong>}
          </p>
          <p className="mt-1 text-xs text-text-dim">{precision.nota} Pendientes: {precision.pendientes}.</p>
        </div>
      )}
      {error && <p role="alert" className="rounded-lg border border-conf-baja/50 p-3 text-sm text-conf-baja">{error}</p>}
      {items == null && !error && <p className="text-sm text-text-muted">Cargando…</p>}
      {items?.length === 0 && (
        <div className="panel border-dashed p-6 text-sm text-text-muted">
          <p className="font-medium text-text">Aún no pediste ningún pronóstico.</p>
          <p className="mt-1">Abre <Link to="/" className="text-accent underline underline-offset-2">Partidos</Link> y elige «Ver pronóstico» en uno.</p>
        </div>
      )}
      <ul className="grid gap-2 md:grid-cols-2">
        {items?.map((i) => (
          <li key={i.id} className="panel p-4 text-sm">
            <p className="text-xs text-text-muted">{fechaLarga(i.date)} · {i.league}</p>
            <p className="mt-1 font-medium">{i.home} <span className="text-text-dim">vs</span> {i.away}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span className="text-text-muted">Pick: <strong className="font-semibold text-text">{i.pick ?? "Sin pronóstico"}</strong></span>
              {i.confidence && <ConfianzaBadge nivel={i.confidence} />}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
