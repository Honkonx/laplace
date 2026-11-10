import { useEffect, useMemo, useRef, type KeyboardEvent } from "react";
import { COMANDOS } from "@/lib/chat";

interface Props {
  valor: string;
  onCambio: (valor: string) => void;
  onEnviar: () => void;
  cargando: boolean;
}

/** Entrada del chat: Enter envía, Shift+Enter salta de línea, «/» ofrece comandos. */
export function Composer({ valor, onCambio, onEnviar, cargando }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    el.style.overflowY = el.scrollHeight > 160 ? "auto" : "hidden";
  }, [valor]);

  const comandos = useMemo(() => {
    const consulta = valor.trim().toLowerCase();
    return consulta.startsWith("/") && !consulta.includes(" ") ? COMANDOS.filter((c) => c.comando.startsWith(consulta)).slice(0, 5) : [];
  }, [valor]);

  function alTeclear(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!cargando && valor.trim()) onEnviar();
    }
  }

  return (
    <div className="border-t border-border p-3">
      {comandos.length > 0 && (
        <ul className="mb-2 overflow-hidden rounded-lg border border-border bg-surface" role="listbox" aria-label="Comandos">
          {comandos.map((c) => (
            <li key={c.comando}>
              <button type="button" role="option" aria-selected="false" onClick={() => onCambio(c.comando)} className="flex min-h-11 w-full items-center justify-between gap-3 px-3 text-left text-sm hover:bg-surface-light">
                <span className="num text-accent">{c.comando}</span>
                <span className="truncate text-text-muted">{c.ayuda}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-end gap-2">
        <textarea ref={ref} rows={1} value={valor} onChange={(e) => onCambio(e.target.value)} onKeyDown={alTeclear}
          placeholder="Pregunta por un partido o un pronóstico" aria-label="Mensaje para Laplace" className="field max-h-40" />
        <button type="button" onClick={onEnviar} disabled={cargando || !valor.trim()} className="btn btn-primary shrink-0">
          Enviar
        </button>
      </div>
      <p className="mt-1.5 hidden text-xs text-text-dim sm:block">Enter envía · Shift+Enter agrega una línea · escribe / para ver comandos</p>
    </div>
  );
}
