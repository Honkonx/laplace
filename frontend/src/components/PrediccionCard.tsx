import { useState } from "react";
import { pedirPrediccion, type ResultadoPrediccion } from "@/lib/api";
import { describirError, type ErrorAmigable } from "@/lib/errores";
import { useAuth } from "@/lib/AuthContext";
import { Escudo } from "./Escudo";
import { PrediccionResultado } from "./PrediccionResultado";

export interface PartidoParaPrediccion {
  matchId: string;
  liga: string;
  local: string;
  visitante: string;
  /** yyyyMMdd, igual que /api/v1/partidos */
  fecha: string;
  hora?: string | null;
  ligaLogo?: string | null;
  localLogo?: string | null;
  visitanteLogo?: string | null;
  /** true cuando el bot tiene modelo histórico para este partido: se marca para ofrecerlo primero. */
  pronosticable?: boolean;
}

interface Props {
  partido: PartidoParaPrediccion;
  /** Si ya hay un análisis (p. ej. lo devolvió el agente), se muestra sin volver a pedirlo. */
  resultadoInicial?: ResultadoPrediccion;
  /** false cuando la tarjeta ya está bajo el título de su liga. */
  mostrarLiga?: boolean;
}

/** Tarjeta de un partido con su pronóstico bajo demanda: llama al endpoint real /prediccion-web. */
export function PrediccionCard({ partido, resultadoInicial, mostrarLiga = true }: Props) {
  const { username } = useAuth();
  const [resultado, setResultado] = useState<ResultadoPrediccion | null>(resultadoInicial ?? null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<ErrorAmigable | null>(null);

  async function pedir() {
    setCargando(true);
    setError(null);
    try {
      setResultado(await pedirPrediccion({ match_id: partido.matchId, local: partido.local, visitante: partido.visitante, liga: partido.liga, fecha: partido.fecha }));
    } catch (e) {
      setError(describirError(e));
    } finally {
      setCargando(false);
    }
  }

  return (
    <article className="panel p-4" aria-label={`${partido.local} contra ${partido.visitante}`}>
      <div className="flex items-center justify-between gap-2 text-xs text-text-muted">
        {mostrarLiga ? (
          <span className="flex min-w-0 items-center gap-1.5">
            {partido.ligaLogo && <Escudo src={partido.ligaLogo} nombre={partido.liga} tamano="h-4 w-4" />}
            <span className="truncate">{partido.liga}</span>
          </span>
        ) : <span />}
        <span className="num shrink-0">
          {partido.pronosticable && <span className="mr-2 text-conf-alta" title="El bot tiene histórico de estos equipos">✔ con pronóstico</span>}
          {partido.hora ?? "Hora por confirmar"}
        </span>
      </div>

      <div className="mt-3 grid gap-2">
        <div className="flex items-center gap-2.5"><Escudo src={partido.localLogo} nombre={partido.local} /><strong className="truncate font-medium">{partido.local}</strong></div>
        <div className="flex items-center gap-2.5"><Escudo src={partido.visitanteLogo} nombre={partido.visitante} /><strong className="truncate font-medium">{partido.visitante}</strong></div>
      </div>

      {!resultado && username && (
        <div className="mt-4 flex items-center justify-between gap-3 border-t border-border pt-3">
          <>
              <span className="text-xs text-text-dim">Pronóstico estadístico bajo demanda</span>
              <button type="button" onClick={() => void pedir()} disabled={cargando} className="btn btn-primary btn-sm">
                {cargando ? "Calculando…" : error ? "Reintentar" : "Ver pronóstico"}
              </button>
          </>
        </div>
      )}

      <div aria-live="polite">
        {cargando && <p className="mt-3 text-xs text-text-muted">Reuniendo datos del partido, puede tardar unos segundos…</p>}
        {error && (
          <div role="alert" className="mt-3 rounded-lg border border-conf-baja/50 p-3 text-xs">
            <p className="font-medium text-conf-baja">{error.titulo}</p>
            <p className="mt-0.5 text-text-muted">{error.detalle}{error.esperaSeg ? ` (reintenta en ${error.esperaSeg} s)` : ""}</p>
          </div>
        )}
      </div>

      {resultado && (
        <div className="mt-4 border-t border-border pt-3">
          <PrediccionResultado resultado={resultado} local={partido.local} visitante={partido.visitante} />
        </div>
      )}
    </article>
  );
}
