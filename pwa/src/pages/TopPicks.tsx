import { useEffect, useState } from "react";
import { obtenerPartidos, pedirPrediccion, type EventoPartido, type ResultadoPrediccion, ApiError } from "@/lib/api";
import { ProbabilidadBar } from "@/components/ProbabilidadBar";
import { ConfianzaBadge } from "@/components/ConfianzaBadge";

// Top Picks — el backend/api/ (FastAPI) NO tiene un endpoint público de "top picks" en el
// contrato web (routers/scheduler.py::POST /top-picks es un cron interno, y app_gateway.py
// exige `x-kairos-key`, que nunca se expone al browser — ver frontend/src/lib/api/). En vez
// de inventar un endpoint nuevo (instrucción explícita de esta ronda: "adaptá el cliente, no
// inventes un contrato nuevo"), esta pantalla arma el ranking en el cliente: pide predicción
// real (POST /api/v1/prediccion-web, el mismo endpoint que ya usa PartidoCard) para los
// partidos del día y ordena por score de consenso real — nunca un número inventado.
//
// Es una acción explícita del usuario (botón), no automática al entrar: calcular una predicción
// dispara trabajo real de motor estadístico por partido — no tiene sentido disparar N cálculos
// solos por abrir la pestaña.
const MAX_CANDIDATOS = 12;
const CONCURRENCIA = 4;

interface PickCalculado {
  evento: EventoPartido;
  liga: string;
  resultado: ResultadoPrediccion;
}

function fechaHoyYyyymmdd(): string {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
}

async function enLotes<T, R>(items: T[], tamanoLote: number, tarea: (item: T) => Promise<R>): Promise<R[]> {
  const resultados: R[] = [];
  for (let i = 0; i < items.length; i += tamanoLote) {
    const lote = items.slice(i, i + tamanoLote);
    resultados.push(...(await Promise.all(lote.map(tarea))));
  }
  return resultados;
}

export function TopPicks() {
  const fecha = fechaHoyYyyymmdd();
  const [candidatos, setCandidatos] = useState<{ evento: EventoPartido; liga: string }[]>([]);
  const [cargandoFixtures, setCargandoFixtures] = useState(true);
  const [calculando, setCalculando] = useState(false);
  const [picks, setPicks] = useState<PickCalculado[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    obtenerPartidos(fecha)
      .then((r) => {
        const lista = r.Stages.flatMap((liga) =>
          liga.Events.filter((e) => e.Eps === "NS").map((evento) => ({ evento, liga: liga.Snm ?? liga.CompN ?? "" })),
        );
        setCandidatos(lista.slice(0, MAX_CANDIDATOS));
      })
      .catch(() => setError("No se pudieron cargar los partidos de hoy."))
      .finally(() => setCargandoFixtures(false));
  }, [fecha]);

  async function calcular() {
    setCalculando(true);
    setError(null);
    try {
      const calculados = await enLotes(candidatos, CONCURRENCIA, async ({ evento, liga }) => {
        const local = evento.T1?.[0]?.Nm ?? "Local";
        const visitante = evento.T2?.[0]?.Nm ?? "Visitante";
        try {
          const resultado = await pedirPrediccion({ match_id: evento.Eid, local, visitante, liga, fecha });
          return { evento, liga, resultado };
        } catch {
          return null;
        }
      });
      const validos = calculados.filter((p): p is PickCalculado => p !== null);
      validos.sort((a, b) => b.resultado.consenso.score_consenso - a.resultado.consenso.score_consenso);
      setPicks(validos.slice(0, 5));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo calcular el ranking ahora.");
    } finally {
      setCalculando(false);
    }
  }

  return (
    <div className="space-y-5 pt-1">
      <div>
        <h1 className="font-display text-2xl font-bold tracking-tight">Top Picks</h1>
        <p className="mt-1 text-sm text-text-muted">Ordenados por consenso real — no un ranking arbitrario.</p>
      </div>

      {!picks && (
        <button
          onClick={() => void calcular()}
          disabled={calculando || cargandoFixtures || candidatos.length === 0}
          className="w-full rounded-xl bg-accent py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          {cargandoFixtures
            ? "Cargando partidos de hoy…"
            : calculando
              ? `Calculando ${candidatos.length} partidos…`
              : candidatos.length === 0
                ? "Sin partidos hoy"
                : `Calcular Top Picks (${candidatos.length} partidos)`}
        </button>
      )}

      {error && <p className="text-sm text-conf-baja">{error}</p>}

      {picks && picks.length === 0 && <p className="text-text-muted">No se pudo calcular ningún pick.</p>}

      {picks && picks.length > 0 && (
        <div className="space-y-3">
          {picks.map(({ evento, liga, resultado }, idx) => {
            const local = evento.T1?.[0]?.Nm ?? "Local";
            const visitante = evento.T2?.[0]?.Nm ?? "Visitante";
            const poisson = resultado.modulos?.poisson;
            return (
              <div key={evento.Eid} className="rounded-xl border border-border bg-surface p-4">
                <div className="flex items-start gap-3">
                  <span className="flex h-7 w-7 flex-none items-center justify-center rounded-lg bg-surface-light font-mono text-xs font-bold text-cyan">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{local} <span className="text-text-dim">vs</span> {visitante}</p>
                    <p className="text-xs text-text-muted">{liga}</p>
                  </div>
                  <ConfianzaBadge nivel={resultado.consenso.confianza_final} score={resultado.consenso.score_consenso} />
                </div>
                <p className="mt-3 text-sm">
                  Pick: <span className="font-semibold text-text">{resultado.consenso.pick_final}</span>
                </p>
                {poisson?.ok && (
                  <div className="mt-3">
                    <ProbabilidadBar
                      local={local}
                      visitante={visitante}
                      probLocal={poisson.prob_local}
                      probEmpate={poisson.prob_empate}
                      probVisitante={poisson.prob_visitante}
                    />
                  </div>
                )}
              </div>
            );
          })}
          <p className="text-center text-[11px] text-text-dim">Análisis estadístico verificable — no una apuesta.</p>
        </div>
      )}
    </div>
  );
}
