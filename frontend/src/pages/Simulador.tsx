import { useState } from "react";
import { simularLiga, type ResultadoSimulador, ApiError } from "@/lib/api";

// Mismos slugs que backend/api/services/top_picks.py::LIGA_SLUG_POR_ID — las ligas top 5 +
// las más consultadas, no la lista completa (evita un dropdown de 18 opciones poco usadas).
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
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl">Simulador de liga</h1>
        <p className="mt-2 max-w-xl text-sm text-text-muted">
          Simula 10.000 veces el resto de la temporada con las probabilidades que estima el
          motor para cada partido pendiente: opciones de campeón, de copa continental y de
          descenso. Son estimaciones, no certezas.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <select
          value={ligaSlug}
          onChange={(e) => setLigaSlug(e.target.value)}
          aria-label="Liga a simular"
          className="field !w-auto"
        >
          {LIGAS.map((l) => (
            <option key={l.slug} value={l.slug}>{l.nombre}</option>
          ))}
        </select>
        <button
          onClick={() => void simular()}
          disabled={cargando}
          className="btn btn-primary"
        >
          {cargando ? "Simulando…" : "Simular temporada"}
        </button>
      </div>

      {error && <p role="alert" className="rounded-lg border border-conf-baja/50 p-3 text-sm text-conf-baja">{error}</p>}

      {equipos.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-4 py-3 font-medium">Equipo</th>
                <th className="px-4 py-3 font-medium">Pos. promedio</th>
                <th className="px-4 py-3 font-medium">% Campeón</th>
                <th className="px-4 py-3 font-medium">% Copa</th>
                <th className="px-4 py-3 font-medium">% Descenso</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {equipos.map(([equipo, datos]) => (
                <tr key={equipo} className="border-b border-border last:border-0 hover:bg-surface">
                  <td className="px-4 py-2.5 font-sans font-medium">{equipo}</td>
                  <td className="px-4 py-2.5 text-text-muted">{datos.posicion_promedio}</td>
                  <td className="px-4 py-2.5 text-conf-alta">{Math.round(datos.prob_campeon * 100)}%</td>
                  <td className="px-4 py-2.5 text-accent">{Math.round(datos.prob_copa * 100)}%</td>
                  <td className="px-4 py-2.5 text-conf-baja">{Math.round(datos.prob_descenso * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
