interface Props {
  /** true cuando el filtro «Con pronóstico» es lo que dejó la lista vacía. */
  porFiltroPronostico: boolean;
  onVerTodos: () => void;
}

export function EstadoVacioPartidos({ porFiltroPronostico, onVerTodos }: Props) {
  return (
    <div className="panel border-dashed p-6 text-sm text-text-muted">
      <p className="font-medium text-text">
        {porFiltroPronostico ? "Ningún partido de esta lista tiene pronóstico." : "No hay partidos próximos con estos filtros."}
      </p>
      {porFiltroPronostico
        ? <button type="button" onClick={onVerTodos} className="btn btn-primary mt-3">Ver todos los partidos</button>
        : <p className="mt-1">Prueba otra fecha o quita la búsqueda.</p>}
    </div>
  );
}
