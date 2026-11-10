import { useState } from "react";
import { PrediccionCard } from "@/components/PrediccionCard";
import { etiquetaHerramienta, fuenteDeModo, respuestasRapidas, type MensajeUI } from "@/lib/chat";
import { MarkdownLite } from "./MarkdownLite";

export type EstadoValoracion = "util" | "no_util" | "enviando" | "error";

interface Props {
  mensaje: MensajeUI;
  valoracion?: EstadoValoracion;
  onValorar?: (mensaje: MensajeUI, util: boolean) => void;
  /** Solo para el último mensaje del hilo: habilita las respuestas rápidas. */
  onResponder?: (texto: string) => void;
}

function horaCorta(iso: string): string {
  const fecha = new Date(iso);
  return Number.isNaN(fecha.getTime()) ? "" : fecha.toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });
}

function BotonCopiar({ texto }: { texto: string }) {
  const [copiado, setCopiado] = useState(false);
  async function copiar() {
    try {
      await navigator.clipboard.writeText(texto);
      setCopiado(true);
      window.setTimeout(() => setCopiado(false), 1600);
    } catch {
      setCopiado(false);
    }
  }
  return (
    <button type="button" onClick={() => void copiar()} className="btn btn-ghost btn-sm" aria-label="Copiar respuesta">
      {copiado ? "Copiado" : "Copiar"}
    </button>
  );
}

function Valoracion({ mensaje, estado, onValorar }: { mensaje: MensajeUI; estado?: EstadoValoracion; onValorar?: Props["onValorar"] }) {
  if (!mensaje.runId || !onValorar) return null;
  if (estado === "util" || estado === "no_util") {
    return <span className="px-2 text-xs text-text-muted" role="status">Gracias, quedó registrada tu valoración.</span>;
  }
  const bloqueado = estado === "enviando";
  return (
    <>
      <button type="button" disabled={bloqueado} onClick={() => onValorar(mensaje, true)} className="btn btn-ghost btn-sm" aria-label="La respuesta fue útil"><span aria-hidden="true">👍</span> Útil</button>
      <button type="button" disabled={bloqueado} onClick={() => onValorar(mensaje, false)} className="btn btn-ghost btn-sm" aria-label="La respuesta no fue útil"><span aria-hidden="true">👎</span> No útil</button>
      {estado === "error" && <span className="text-xs text-conf-baja" role="alert">No se pudo guardar.</span>}
    </>
  );
}

export function MensajeBurbuja({ mensaje, valoracion, onValorar, onResponder }: Props) {
  if (mensaje.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[88%] rounded-xl rounded-br-sm border border-border bg-surface-light px-3.5 py-2.5 sm:max-w-[75%]">
          <p className="whitespace-pre-wrap break-words text-[15px]">{mensaje.content}</p>
          <p className="num mt-1 text-right text-[11px] text-text-dim">{horaCorta(mensaje.creado)}</p>
        </div>
      </div>
    );
  }

  const fuente = fuenteDeModo(mensaje.modo);
  const partido = mensaje.prediccion
    ? { matchId: mensaje.prediccion.partido_id, liga: mensaje.prediccion.liga, local: mensaje.prediccion.local, visitante: mensaje.prediccion.visitante, fecha: "" }
    : null;

  return (
    <div className="space-y-1.5">
      {mensaje.herramienta && (
        <p className="flex items-center gap-1.5 pl-1 text-xs text-text-muted">
          <span aria-hidden="true" className="inline-block h-px w-3 bg-border" />
          Consultó la herramienta
          <span className="chip num" title={mensaje.herramienta}>{etiquetaHerramienta(mensaje.herramienta)}</span>
        </p>
      )}
      <div className="max-w-[94%] rounded-xl rounded-bl-sm border border-border bg-surface px-3.5 py-3 sm:max-w-[85%]">
        <MarkdownLite texto={mensaje.content} />
        {partido && mensaje.prediccion && (
          <div className="mt-3"><PrediccionCard partido={partido} resultadoInicial={mensaje.prediccion} /></div>
        )}
        {onResponder && respuestasRapidas(mensaje.herramienta).length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Respuestas rápidas">
            {respuestasRapidas(mensaje.herramienta).map((r) => (
              <button key={r} type="button" onClick={() => onResponder(r)} className="btn btn-sm">{r === "bot" ? "Análisis del bot" : "Hipótesis con IA"}</button>
            ))}
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-x-1 gap-y-1 border-t border-border pt-2">
          {fuente && (
            <span className={`chip ${fuente.tipo === "ia" ? "border-accent/60 text-accent" : ""}`} title={fuente.detalle}>
              {fuente.tipo === "ia" ? "Respuesta con IA" : fuente.etiqueta === "Por reglas" ? "Respuesta por reglas" : fuente.etiqueta}
              {fuente.detalle && fuente.tipo === "ia" && <span className="num text-text-dim">{fuente.detalle}</span>}
            </span>
          )}
          <span className="num text-[11px] text-text-dim">{horaCorta(mensaje.creado)}</span>
          <span className="ml-auto flex items-center">
            <BotonCopiar texto={mensaje.content} />
            <Valoracion mensaje={mensaje} estado={valoracion} onValorar={onValorar} />
          </span>
        </div>
        {fuente?.detalle && fuente.tipo !== "ia" && <p className="mt-1 text-xs text-text-dim">{fuente.detalle}</p>}
      </div>
    </div>
  );
}

export function IndicadorEscritura() {
  return (
    <div className="max-w-[94%] rounded-xl rounded-bl-sm border border-border bg-surface px-3.5 py-3" role="status" aria-live="polite">
      <span className="flex items-center gap-2 text-sm text-text-muted">
        <span className="flex gap-1" aria-hidden="true">
          <span className="typing-dot h-1.5 w-1.5 rounded-full bg-text-muted" />
          <span className="typing-dot h-1.5 w-1.5 rounded-full bg-text-muted" />
          <span className="typing-dot h-1.5 w-1.5 rounded-full bg-text-muted" />
        </span>
        Laplace está revisando los datos…
      </span>
    </div>
  );
}
