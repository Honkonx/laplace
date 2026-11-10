import type { Conteo, ModoPronostico } from "@/lib/pronosticables";

interface Props {
  modo: ModoPronostico;
  conteo: Conteo;
  onCambiar: (modo: ModoPronostico) => void;
}

/** Control segmentado «Con pronóstico (N) | Todos (M)»; cada opción mide 44 px de alto como mínimo. */
export function SelectorPronostico({ modo, conteo, onCambiar }: Props) {
  const opciones: Array<{ id: ModoPronostico; etiqueta: string }> = [
    { id: "con", etiqueta: `Con pronóstico (${conteo.con})` },
    { id: "todos", etiqueta: `Todos (${conteo.total})` },
  ];
  return (
    <div role="group" aria-label="Qué partidos mostrar" className="flex flex-wrap gap-1">
      {opciones.map((o) => (
        <button key={o.id} type="button" aria-pressed={modo === o.id} onClick={() => onCambiar(o.id)}
          className={`btn ${modo === o.id ? "btn-primary" : ""}`}>{o.etiqueta}</button>
      ))}
    </div>
  );
}
