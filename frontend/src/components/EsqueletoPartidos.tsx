/** Marcadores de carga de la lista de partidos; sin texto, el contenedor padre lleva aria-busy. */
export function EsqueletoPartidos({ tarjetas = 3 }: { tarjetas?: number }) {
  return (
    <div data-testid="esqueleto-partidos" className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-hidden="true">
      {Array.from({ length: tarjetas }, (_, i) => (
        <div key={i} className="panel animate-pulse space-y-3 p-4">
          <div className="h-3 w-1/3 rounded bg-surface-light" />
          <div className="h-5 w-3/4 rounded bg-surface-light" />
          <div className="h-5 w-2/3 rounded bg-surface-light" />
          <div className="h-11 w-full rounded bg-surface-light" />
        </div>
      ))}
    </div>
  );
}
