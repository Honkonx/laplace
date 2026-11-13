import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ligasSimulables, simularLiga, type LigaSimulable, type ResultadoSimulador, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/AuthContext";

// El simulador es de los planes pro y max y de los administradores (el servidor lo exige: esta pantalla solo lo anticipa).
const PLANES_CON_SIMULADOR = ["pro", "max"];

export function Simulador() {
  const { username, plan, rol } = useAuth();
  const conAcceso = rol === "admin" || (plan !== null && PLANES_CON_SIMULADOR.includes(plan));
  const [ligas, setLigas] = useState<LigaSimulable[]>([]);
  const [ligaSlug, setLigaSlug] = useState("premier");
  const [resultado, setResultado] = useState<ResultadoSimulador | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ligasSimulables()
      .then((r) => {
        const disponibles = r.ligas.filter((l) => l.disponible);
        setLigas(disponibles);
        if (disponibles.length > 0 && !disponibles.some((l) => l.slug === "premier")) setLigaSlug(disponibles[0].slug);
      })
      .catch(() => setLigas([]));
  }, []);

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
        <p className="mt-2 max-w-xl text-sm text-text-muted">
          Simula el resto de la temporada con los resultados hasta hoy y el modelo propio: opciones de campeón,
          de copa continental y de descenso. Son estimaciones, no certezas.
        </p>
      </div>

      {!conAcceso && (
        <div role="note" className="rounded-xl border border-border p-4 text-sm">
          <p className="font-medium">El simulador es de los planes pro y max</p>
          <p className="mt-1 text-text-muted">
            {username ? `Tu plan es ${(plan ?? "free").toUpperCase()}.` : "Inicia sesión con una cuenta de plan pro o max."}
          </p>
          {!username && <Link to="/entrar" className="btn btn-primary mt-3 inline-flex">Entrar</Link>}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <select
          value={ligaSlug}
          onChange={(e) => setLigaSlug(e.target.value)}
          aria-label="Liga a simular"
          className="field !w-auto"
        >
          {(ligas.length > 0 ? ligas : [{ slug: "premier", nombre: "Premier League", disponible: true }]).map((l) => (
            <option key={l.slug} value={l.slug}>{l.nombre}</option>
          ))}
        </select>
        <button
          onClick={() => void simular()}
          disabled={cargando || !conAcceso}
          title={conAcceso ? undefined : "Solo planes pro y max"}
          className="btn btn-primary"
        >
          {cargando ? "Simulando…" : "Simular temporada"}
        </button>
      </div>

      {error && <p role="alert" className="rounded-lg border border-conf-baja/50 p-3 text-sm text-conf-baja">{error}</p>}

      {resultado?.datos_hasta && (
        <p className="text-xs text-text-muted">
          {resultado.n_simulaciones?.toLocaleString("es-CL")} simulaciones · {resultado.partidos_jugados} partidos jugados · {resultado.partidos_pendientes} por jugar · datos hasta {resultado.datos_hasta}
        </p>
      )}

      {equipos.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-4 py-3 font-medium">Equipo</th>
                <th className="px-4 py-3 font-medium">Pos. promedio</th>
                <th className="px-4 py-3 font-medium">Puntos (90 %)</th>
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
                  <td className="px-4 py-2.5 text-text-muted">{datos.puntos ? `${Math.round(datos.puntos.p05)}–${Math.round(datos.puntos.p95)}` : "—"}</td>
                  <td className="px-4 py-2.5 text-conf-alta">{Math.round(datos.prob_campeon * 100)}%</td>
                  <td className="px-4 py-2.5 text-accent">{Math.round(datos.prob_copa * 100)}%</td>
                  <td className="px-4 py-2.5 text-conf-baja">{Math.round(datos.prob_descenso * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {resultado?.aviso && <p className="text-xs text-text-dim">{resultado.aviso}</p>}
    </div>
  );
}
