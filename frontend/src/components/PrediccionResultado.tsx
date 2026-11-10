import type { ResultadoPrediccion } from "@/lib/api";
import { CONFIANZA_DEFINICION, construirVista, pct, textoPick } from "@/lib/prediccion";
import { ConfianzaBadge } from "./ConfianzaBadge";
import { ProbabilidadBar } from "./ProbabilidadBar";

interface Props {
  resultado: ResultadoPrediccion;
  local: string;
  visitante: string;
}

/** Vista de un análisis ya calculado. Solo muestra lo que devolvió el motor; no calcula nada. */
export function PrediccionResultado({ resultado, local, visitante }: Props) {
  const vista = construirVista(resultado);

  if (!vista.conPronostico || !vista.probs) {
    return (
      <div className="rounded-lg border border-border bg-surface-light p-3 text-sm" role="status">
        <p className="font-medium text-text">Sin pronóstico</p>
        <p className="mt-1 text-text-muted">{vista.motivoSinPronostico}</p>
        {resultado.motivos_sin_pronostico && resultado.motivos_sin_pronostico.length > 0 && (
          <ul className="mt-1 list-disc pl-4 text-xs text-text-muted">
            {resultado.motivos_sin_pronostico.slice(0, 3).map((motivo) => <li key={motivo}>{motivo}</li>)}
          </ul>
        )}
        {resultado.referencia_tasa_base?.pct_local != null && (
          <p className="mt-2 text-xs text-text-muted">
            <span className="text-text-dim">Referencia, no pronóstico ({resultado.referencia_tasa_base.nivel === "liga" ? "esta liga" : "promedio general"}): </span>
            Local <span className="num">{pct((resultado.referencia_tasa_base.pct_local ?? 0) / 100)}%</span> · Empate <span className="num">{pct((resultado.referencia_tasa_base.pct_empate ?? 0) / 100)}%</span> · Visitante <span className="num">{pct((resultado.referencia_tasa_base.pct_visitante ?? 0) / 100)}%</span>. No distingue a estos dos equipos.
          </p>
        )}
        <p className="mt-2 text-xs text-text-dim">
          No estimar también es un resultado: preferimos no mostrar un número antes que inventarlo.
          {resultado.calidad_datos?.sources?.length ? ` Fuentes con datos: ${resultado.calidad_datos.sources.join(", ")}.` : ""}
        </p>
      </div>
    );
  }

  const odds = resultado.odds_info && !resultado.odds_info.startsWith("Sin odds") ? resultado.odds_info : null;

  return (
    <div className="space-y-3">
      <ProbabilidadBar local={local} visitante={visitante} probLocal={vista.probs.local} probEmpate={vista.probs.empate} probVisitante={vista.probs.visitante} />

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="text-sm">
          <span className="text-text-muted">Pick: </span>
          <strong className="font-semibold">{vista.pick ? textoPick(vista.pick, local, visitante) : ""}</strong>
        </p>
        {vista.confianza && <ConfianzaBadge nivel={vista.confianza} />}
      </div>
      {vista.confianza && <p className="text-xs text-text-muted">{CONFIANZA_DEFINICION[vista.confianza]}</p>}
      {resultado.nivel_evidencia && (
        <p className="text-xs text-text-dim">Evidencia {resultado.nivel_evidencia.codigo}: {resultado.nivel_evidencia.etiqueta}</p>
      )}

      {vista.desactualizadoDias != null && (
        <p className="rounded-md border border-conf-media/50 px-2.5 py-1.5 text-xs text-conf-media" role="note">
          Modelo desactualizado: los ratings históricos tienen {Math.round(vista.desactualizadoDias / 30)} meses. La confianza ya está rebajada.
        </p>
      )}

      {vista.tasaBase && (
        <p className="text-xs text-text-muted">
          <span className="text-text-dim">Tasa base de la liga: </span>
          Local <span className="num">{pct(vista.tasaBase.local)}%</span> · Empate <span className="num">{pct(vista.tasaBase.empate)}%</span> · Visitante <span className="num">{pct(vista.tasaBase.visitante)}%</span>
          {vista.tasaBasePartidos ? ` (${vista.tasaBasePartidos.toLocaleString("es-CL")} partidos)` : ""}
        </p>
      )}

      {vista.modulos.length > 0 && (
        <details className="group text-xs">
          <summary className="cursor-pointer select-none py-1 text-text-muted hover:text-text">
            Cómo se calculó · {vista.modulos.length} {vista.modulos.length === 1 ? "modelo" : "modelos"}, {vista.coinciden} de {vista.totalModulos} coinciden con el pick
          </summary>
          <ul className="mt-2 space-y-1.5">
            {vista.modulos.map((m) => (
              <li key={m.id} className="grid grid-cols-[1fr_auto] items-center gap-x-3">
                <span className="truncate text-text">{m.etiqueta}</span>
                <span className="num text-text-muted">{m.pesoPct}% del peso</span>
                <span className="col-span-2 mb-0.5 h-1 overflow-hidden rounded-full bg-surface-light" aria-hidden="true">
                  <span className="block h-full bg-accent" style={{ width: `${m.pesoPct}%` }} />
                </span>
                {m.probs && (
                  <span className="col-span-2 num text-[11px] text-text-muted">
                    1X2 módulo: L {(m.probs.local * 100).toFixed(1)}% · E {(m.probs.empate * 100).toFixed(1)}% · V {(m.probs.visitante * 100).toFixed(1)}%
                  </span>
                )}
                {!m.coincide && <span className="col-span-2 text-text-dim">Este modelo no coincide con el pick.</span>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {odds && (
        <p className="text-xs text-text-muted">
          <span className="text-text-dim">Dato del análisis (cuotas del mercado, informativo): </span>
          {odds}
        </p>
      )}

      <p className="border-t border-border pt-2 text-xs text-text-dim">
        Estimación estadística, no una certeza. Cada resultado puede salir distinto de lo más probable.
      </p>
    </div>
  );
}
