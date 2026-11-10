import { useEffect, useState } from "react";
import type { ErrorAmigable } from "@/lib/errores";

interface Props {
  error: ErrorAmigable;
  onReintentar?: () => void;
  /** Para límites de IA diarios: seguir sin IA. */
  onSeguirSinIa?: () => void;
}

/** Error del chat: dice qué pasó, cuánto esperar y qué hacer. La cuenta atrás habilita el reintento. */
export function AvisoError({ error, onReintentar, onSeguirSinIa }: Props) {
  const [restante, setRestante] = useState(error.esperaSeg ?? 0);

  useEffect(() => {
    setRestante(error.esperaSeg ?? 0);
    if (!error.esperaSeg) return;
    const id = window.setInterval(() => setRestante((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => window.clearInterval(id);
  }, [error]);

  const puedeReintentar = error.reintentable && onReintentar && restante === 0;

  return (
    <div role="alert" className="rounded-lg border border-conf-baja/50 bg-surface p-3 text-sm">
      <p className="font-medium text-conf-baja">{error.titulo}</p>
      <p className="mt-0.5 text-text-muted">{error.detalle}</p>
      {restante > 0 && <p className="num mt-1 text-xs text-text-muted">Puedes reintentar en {restante} s.</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        {error.reintentable && onReintentar && <button type="button" onClick={onReintentar} disabled={!puedeReintentar} className="btn btn-sm">Reintentar</button>}
        {error.tipo === "limite" && onSeguirSinIa && <button type="button" onClick={onSeguirSinIa} className="btn btn-sm">Seguir sin IA</button>}
      </div>
    </div>
  );
}
