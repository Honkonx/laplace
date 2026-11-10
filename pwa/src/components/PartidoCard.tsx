import { useState } from "react";
import { pedirPrediccion, type EventoPartido, type ResultadoPrediccion, ApiError } from "@/lib/api";
import { ProbabilidadBar } from "./ProbabilidadBar";
import { ConfianzaBadge } from "./ConfianzaBadge";

function horaChile(esd?: string | number): string {
  if (esd == null) return "";
  const texto = String(esd);
  if (texto.length < 12) return "";
  const hora = texto.slice(8, 12);
  return `${hora.slice(0, 2)}:${hora.slice(2, 4)}`;
}

// Tarjeta de partido — toque para expandir la predicción in-place (sin navegar a otra pantalla,
// más rápido en el celular que un push de navegación por cada partido). Misma lógica que
// frontend/src/components/PartidoCard.tsx, ajustada a densidad táctil (padding más grande,
// ancho completo en vez de grid de 2 columnas — layout de una sola columna, patrón app móvil).
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

  return (
    <button
      type="button"
      onClick={() => {
        if (!resultado && !cargando) void pedir();
      }}
      className="w-full rounded-xl border border-border bg-surface p-4 text-left transition-colors active:border-accent/40"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{local} <span className="text-text-dim">vs</span> {visitante}</p>
          <p className="text-xs text-text-muted">{horaChile(evento.Esd)} hora Chile</p>
        </div>
        {!resultado && (
          <span className="shrink-0 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white">
            {cargando ? "Calculando…" : "Predecir"}
          </span>
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
            <ConfianzaBadge nivel={resultado.consenso.confianza_final} score={resultado.consenso.score_consenso} />
          </div>
          {marcadorProbable && (
            <p className="font-mono text-xs text-text-muted">Marcador probable: {marcadorProbable}</p>
          )}
        </div>
      )}
      {resultado && !tienePronostico && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="text-sm font-medium text-conf-media">Análisis no publicable todavía</p>
          <p className="mt-1 text-xs text-text-muted">
            {resultado.calidad_datos?.reason ?? "Faltan datos verificables para emitir un pronóstico estadístico."}
          </p>
          {resultado.calidad_datos?.sources?.length ? (
            <p className="mt-2 text-[11px] text-text-dim">Fuentes: {resultado.calidad_datos.sources.join(", ")}</p>
          ) : null}
        </div>
      )}
    </button>
  );
}
