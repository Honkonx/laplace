// Firma visual de Laplace: nunca un pick opaco, siempre la distribución Local / Empate /
// Visitante como barra segmentada con sus números al lado (el color no es el único portador
// de significado). Se reutiliza en toda tarjeta o detalle de partido.
interface Props {
  local: string;
  visitante: string;
  probLocal: number;
  probEmpate: number;
  probVisitante: number;
}

export function ProbabilidadBar({ local, visitante, probLocal, probEmpate, probVisitante }: Props) {
  const filas = [
    { clave: "local", nombre: local, valor: Math.round(probLocal * 100), color: "bg-local" },
    { clave: "empate", nombre: "Empate", valor: Math.round(probEmpate * 100), color: "bg-draw" },
    { clave: "visitante", nombre: visitante, valor: Math.round(probVisitante * 100), color: "bg-away" },
  ];
  const descripcion = filas.map((f) => `${f.nombre} ${f.valor}%`).join(", ");

  return (
    <div className="w-full">
      <div role="img" aria-label={`Probabilidad estimada: ${descripcion}`} className="flex h-3 w-full gap-px overflow-hidden rounded-[4px] bg-surface-light">
        {filas.map((f) => (
          <div key={f.clave} className={`${f.color} h-full transition-[width] duration-500 ease-out`} style={{ width: `${f.valor}%` }} />
        ))}
      </div>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-xs" aria-hidden="true">
        {filas.map((f, i) => (
          <div key={f.clave} className={i === 1 ? "text-center" : i === 2 ? "text-right" : ""}>
            <dt className={`flex items-center gap-1.5 text-text-muted ${i === 1 ? "justify-center" : i === 2 ? "justify-end" : ""}`}>
              <span className={`inline-block h-2 w-2 shrink-0 rounded-[2px] ${f.color}`} />
              <span className="truncate">{f.nombre}</span>
            </dt>
            <dd className="num mt-0.5 text-base font-medium text-text">{f.valor}%</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
