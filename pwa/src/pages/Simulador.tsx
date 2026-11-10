import { useState } from "react";
import { simularLiga, type ResultadoSimulador, ApiError } from "@/lib/api";

// Mismos slugs que backend/api/services/top_picks.py::LIGA_SLUG_POR_ID — igual que
// frontend/src/pages/Simulador.tsx (top 5 ligas, no el dropdown completo de 18).
const LIGAS = [
  { slug: "premier", nombre: "Premier League" },
  { slug: "laliga", nombre: "La Liga" },
  { slug: "seriea", nombre: "Serie A" },
  { slug: "bundesliga", nombre: "Bundesliga" },
  { slug: "ligue1", nombre: "Ligue 1" },
];

export function Simulador() {
  const [ligaSlug, setLigaSlug] = useState(LIGAS[0].slug);
  const [resultado, setResultado] = useState<ResultadoSimulador | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function simular() {
    setCargando(true);
    setError(null);
    setResultado(null);
    try {
      const r = await simularLiga(ligaSlug);
      if (!r.ok) {
        setError(r.razon ?? "No se pudo simular esta liga ahora mismo.");
        return;
      }
      setResultado(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo correr la simulación.");
    } finally {
      setCargando(false);
    }
  }

  const equipos = resultado?.tabla
    ? Object.entries(resultado.tabla).sort((a, b) => b[1].prob_campeon - a[1].prob_campeon)
    : [];

  return (
    <div className="space-y-5 pt-1">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight">Simulador de liga</h1>
        <p className="mt-2 text-sm text-text-muted">
          10.000 simulaciones del resto de la temporada con las probabilidades reales del motor
          — probabilidad de campeón, de copa continental y de descenso.
        </p>
      </div>

      <select
        value={ligaSlug}
        onChange={(e) => setLigaSlug(e.target.value)}
        className="w-full rounded-xl border border-border bg-surface px-3 py-2.5 text-sm text-text"
      >
        {LIGAS.map((l) => (
          <option key={l.slug} value={l.slug}>{l.nombre}</option>
        ))}
      </select>
      <button
        onClick={() => void simular()}
        disabled={cargando}
        className="w-full rounded-xl bg-accent py-3 text-sm font-semibold text-white disabled:opacity-50"
      >
        {cargando ? "Simulando…" : "Simular temporada"}
      </button>

      {error && <p className="text-sm text-conf-baja">{error}</p>}

      {equipos.length > 0 && (
        <div className="space-y-2">
          {equipos.map(([equipo, datos], idx) => (
            <div key={equipo} className="flex items-center gap-3 rounded-xl border border-border bg-surface p-3">
              <span className="flex h-7 w-7 flex-none items-center justify-center rounded-lg bg-surface-light font-mono text-xs font-bold text-text-muted">
                {idx + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{equipo}</p>
                <p className="font-mono text-[11px] text-text-dim">Pos. promedio {datos.posicion_promedio}</p>
              </div>
              <div className="flex flex-none gap-3 text-right font-mono text-xs">
                <span className="text-conf-alta">{Math.round(datos.prob_campeon * 100)}%<br /><span className="text-[9px] text-text-dim">camp.</span></span>
                <span className="text-accent">{Math.round(datos.prob_copa * 100)}%<br /><span className="text-[9px] text-text-dim">copa</span></span>
                <span className="text-conf-baja">{Math.round(datos.prob_descenso * 100)}%<br /><span className="text-[9px] text-text-dim">desc.</span></span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
