import type { GolesPorEquipoResumen, GolesEquipo } from "@/lib/api";

const aPct = (valor: number) => Math.round(valor * 100);

function FilaEquipo({ nombre, goles }: { nombre: string; goles: GolesEquipo }) {
  const tramos = [["0", goles.p0], ["1", goles.p1], ["2", goles.p2], ["3+", goles.p3_o_mas]] as const;
  return (
    <li className="space-y-1">
      <p className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="truncate font-medium text-text">{nombre}</span>
        <span className="text-text-muted">
          <span className="num">{goles.esperados.toFixed(1)}</span> goles esperados · marca <span className="num">{aPct(goles.marca)}%</span>
        </span>
      </p>
      <div className="grid grid-cols-4 gap-1.5">
        {tramos.map(([etiqueta, p]) => (
          <div key={etiqueta} className="text-[11px] text-text-muted">
            <div className="h-1 overflow-hidden rounded-full bg-surface-light" aria-hidden="true">
              <div className="h-full bg-accent" style={{ width: `${aPct(p)}%` }} />
            </div>
            {etiqueta} gol{etiqueta === "1" ? "" : "es"} <span className="num">{aPct(p)}%</span>
          </div>
        ))}
      </div>
    </li>
  );
}

/** Goles por equipo del modelo propio. No renderiza nada si el modelo no los validó (campo ausente o null). */
export function GolesPorEquipo({ goles, local, visitante, marcador }: { goles?: GolesPorEquipoResumen | null; local: string; visitante: string; marcador?: string | null }) {
  if (!goles || !goles.local || !goles.visitante) return null;
  const acierto = goles.acierto_historico_marcador;
  return (
    <section className="mt-3 space-y-2 text-xs" aria-label="Goles por equipo">
      <h3 className="text-sm font-semibold text-text">Goles por equipo</h3>
      <ul className="space-y-2">
        <FilaEquipo nombre={local} goles={goles.local} />
        <FilaEquipo nombre={visitante} goles={goles.visitante} />
      </ul>
      {marcador && (
        <p className="text-text-muted">
          Marcador más probable <span className="num">{marcador}</span>
          {acierto != null && <> · acierta ~<span className="num">{aPct(acierto)}</span> % de las veces</>}
        </p>
      )}
      <p className="text-text-dim">Estimación propia; donde hay cuotas, la cuota es mejor guía.</p>
    </section>
  );
}
