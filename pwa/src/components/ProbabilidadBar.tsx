// El elemento de firma visual de Laplace: en vez de un pick opaco, siempre se muestra la
// distribución real de probabilidad Local/Empate/Visitante como una barra segmentada — la idea
// central del producto (product-philosophy.md: predicciones trazables, no un score opaco) hecha
// visible. Idéntico a frontend/src/components/ProbabilidadBar.tsx — misma identidad visual en
// las dos superficies web.
interface Props {
  local: string;
  visitante: string;
  probLocal: number;
  probEmpate: number;
  probVisitante: number;
}

export function ProbabilidadBar({ local, visitante, probLocal, probEmpate, probVisitante }: Props) {
  const pl = Math.round(probLocal * 100);
  const pe = Math.round(probEmpate * 100);
  const pv = Math.round(probVisitante * 100);

  return (
    <div className="w-full">
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-light">
        <div
          className="h-full bg-accent transition-[width] duration-700 ease-out"
          style={{ width: `${pl}%` }}
          title={`${local}: ${pl}%`}
        />
        <div
          className="h-full bg-text-dim transition-[width] duration-700 ease-out"
          style={{ width: `${pe}%` }}
          title={`Empate: ${pe}%`}
        />
        <div
          className="h-full bg-cyan transition-[width] duration-700 ease-out"
          style={{ width: `${pv}%` }}
          title={`${visitante}: ${pv}%`}
        />
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-xs text-text-muted">
        <span className="text-accent">{pl}%</span>
        <span>{pe}%</span>
        <span className="text-cyan">{pv}%</span>
      </div>
    </div>
  );
}
