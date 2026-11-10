import type { Conteo, Vista } from "@/lib/pronosticables";

export function ControlVista({ vista, conteo, onChange }: { vista: Vista; conteo: Conteo; onChange: (vista: Vista) => void }) {
  const opciones: { id: Vista; texto: string }[] = [
    { id: "con", texto: `Con pronóstico (${conteo.con})` },
    { id: "todos", texto: `Todos (${conteo.todos})` },
  ];
  return <div role="group" aria-label="Vista de partidos" className="flex gap-1 rounded-xl border border-border bg-surface p-1">
    {opciones.map((opcion) => <button key={opcion.id} type="button" aria-pressed={vista === opcion.id} onClick={() => onChange(opcion.id)}
      className={`min-h-11 flex-1 rounded-lg px-2 text-sm ${vista === opcion.id ? "bg-accent text-white" : "text-text-muted"}`}>{opcion.texto}</button>)}
  </div>;
}

export function EstadoVacio({ onVerTodos }: { onVerTodos: () => void }) {
  return <div className="rounded-xl border border-dashed border-border p-4 text-center">
    <p className="text-sm text-text-muted">Ningún partido con pronóstico en esta lista.</p>
    <button type="button" onClick={onVerTodos} className="mt-3 min-h-11 rounded-lg bg-accent px-4 text-sm font-medium text-white">Ver todos los partidos</button>
  </div>;
}

export function EsqueletosCarga() {
  return <div aria-busy="true" aria-label="Cargando partidos" className="space-y-3">
    {[0, 1, 2].map((i) => <div key={i} className="h-32 animate-pulse rounded-xl border border-border bg-surface" />)}
  </div>;
}
