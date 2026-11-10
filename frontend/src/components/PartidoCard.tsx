import { useState } from "react";
import { pedirPrediccion, type EventoPartido, type ModuloResultado, type ResultadoPrediccion, ApiError } from "@/lib/api";
import { ProbabilidadBar } from "./ProbabilidadBar";
import { ConfianzaBadge } from "./ConfianzaBadge";

// El backend (services/form_recent.py y services/h2h.py) devuelve más campos por módulo de
// los que declara `ModuloResultado` en lib/api.ts (que solo tipa lo común a todos los
// módulos). Se extiende acá, en el único componente que los lee, en vez de tocar lib/api.ts.
interface ModuloForma extends ModuloResultado {
  forma_local_wins?: number;
  forma_visit_wins?: number;
}
interface ModuloH2H extends ModuloResultado {
  h2h_local_wins?: number;
  h2h_visit_wins?: number;
  h2h_empates?: number;
  h2h_total?: number;
  dominador?: "Local" | "Visitante" | "Empate";
}

function horaChile(esd?: string | number): string {
  if (esd == null) return "";
  const texto = String(esd);
  if (texto.length < 12) return "";
  const hora = texto.slice(8, 12);
  return `${hora.slice(0, 2)}:${hora.slice(2, 4)}`;
}

function PuntosForma({ wins }: { wins: number }) {
  return (
    <span className="inline-flex gap-0.5" title={`${wins} victorias en los últimos 5 partidos`}>
      {Array.from({ length: 5 }).map((_, i) => (
        <span
          key={i}
          className={`h-1.5 w-1.5 rounded-full ${i < wins ? "bg-conf-alta" : "bg-surface-light"}`}
        />
      ))}
    </span>
  );
}

function resumenH2H(h2h: ModuloH2H | null | undefined, local: string, visitante: string): string | null {
  if (!h2h?.ok || h2h.h2h_total == null || h2h.h2h_total < 3) return null;
  const { h2h_local_wins = 0, h2h_visit_wins = 0, h2h_empates = 0, h2h_total, dominador } = h2h;
  const marcador = `${h2h_local_wins}V-${h2h_empates}E-${h2h_visit_wins}V en ${h2h_total} partidos`;
  if (dominador === "Local") return `${local} gana el historial reciente (${marcador})`;
  if (dominador === "Visitante") return `${visitante} gana el historial reciente (${marcador})`;
  return `Historial directo parejo (${marcador})`;
}

export function PartidoCard({ evento, liga, fecha }: { evento: EventoPartido; liga: string; fecha: string }) {
  const local = evento.T1?.[0]?.Nm ?? "Local";
  const visitante = evento.T2?.[0]?.Nm ?? "Visitante";
  const [resultado, setResultado] = useState<ResultadoPrediccion | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pedir() {
    setCargando(true);
    setError(null);
    try {
      setResultado(
        await pedirPrediccion({ match_id: evento.Eid, local, visitante, liga, fecha }),
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo calcular la predicción. Probá de nuevo.");
    } finally {
      setCargando(false);
    }
  }

  const consenso = resultado?.consenso;
  const probs = consenso?.prob_ponderada
    ?? (resultado?.modulos?.historico?.ok
      ? {
          local: resultado.modulos.historico.prob_local,
          empate: resultado.modulos.historico.prob_empate,
          visitante: resultado.modulos.historico.prob_visitante,
        }
      : resultado?.modulos?.poisson?.ok
        ? {
            local: resultado.modulos.poisson.prob_local,
            empate: resultado.modulos.poisson.prob_empate,
            visitante: resultado.modulos.poisson.prob_visitante,
          }
        : null);
  const tienePronostico = Boolean(
    consenso &&
    consenso.total_modulos > 0 &&
    consenso.pick_final &&
    !consenso.pick_final.startsWith("Sin pronóstico") &&
    probs,
  );
  const marcadorProbable =
    resultado?.modulos?.historico?.marcador_probable ?? resultado?.modulos?.poisson?.marcador_probable;
  const forma = resultado?.modulos?.forma as ModuloForma | null | undefined;
  const h2h = resultado?.modulos?.h2h as ModuloH2H | null | undefined;
  const textoH2H = resumenH2H(h2h, local, visitante);
  const textoOdds =
    resultado?.odds_info && !resultado.odds_info.startsWith("Sin odds") ? resultado.odds_info : null;

  return (
    <div className="rounded-xl border border-border bg-surface p-4 transition-colors hover:border-accent/40">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{local} <span className="text-text-dim">vs</span> {visitante}</p>
          <p className="text-xs text-text-muted">{horaChile(evento.Esd)} hora Chile</p>
        </div>
        {!resultado && (
          <button
            onClick={() => void pedir()}
            disabled={cargando}
            className="shrink-0 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent/90 disabled:opacity-50"
          >
            {cargando ? "Calculando…" : "Predecir"}
          </button>
        )}
      </div>

      {error && <p className="mt-3 text-xs text-conf-baja">{error}</p>}

      {resultado && tienePronostico && probs && (
        <div className="mt-4 space-y-3 border-t border-border pt-3">
          <ProbabilidadBar
            local={local}
            visitante={visitante}
            probLocal={probs.local}
            probEmpate={probs.empate}
            probVisitante={probs.visitante}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm">
              Pick: <span className="font-semibold text-text">{resultado.consenso.pick_final}</span>
            </p>
            <ConfianzaBadge nivel={resultado.consenso.confianza_final} />
          </div>
          {marcadorProbable && (
            <p className="font-mono text-xs text-text-muted">Marcador probable: {marcadorProbable}</p>
          )}

          {forma?.ok && forma.forma_local_wins != null && forma.forma_visit_wins != null && (
            <div className="flex items-center justify-between text-xs text-text-muted">
              <span className="flex items-center gap-1.5">
                <span className="max-w-[6.5rem] truncate">{local}</span>
                <PuntosForma wins={forma.forma_local_wins} />
              </span>
              <span className="text-text-dim">forma (últ. 5)</span>
              <span className="flex items-center gap-1.5">
                <PuntosForma wins={forma.forma_visit_wins} />
                <span className="max-w-[6.5rem] truncate">{visitante}</span>
              </span>
            </div>
          )}

          {textoH2H && <p className="text-xs text-text-muted">{textoH2H}</p>}

          {textoOdds && (
            <p className="text-xs text-text-muted">
              <span className="text-text-dim">Cuota de referencia del análisis:</span> {textoOdds}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
