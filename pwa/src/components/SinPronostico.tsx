import type { TasaBaseLiga } from "@/lib/api";

interface Props {
  motivos?: string[];
  referencia?: TasaBaseLiga | null;
  detalle?: string;
  fuentes?: string[];
}

const redondear = (valor?: number | null) => Math.round(valor ?? 0);

/** Explica por qué no hay pronóstico. La tasa base es una referencia histórica, nunca un pick. */
export function SinPronostico({ motivos, referencia, detalle, fuentes }: Props) {
  const lista = (motivos ?? []).slice(0, 3);
  return (
    <div className="rounded-lg border border-orange-400/30 bg-orange-400/10 p-3 text-xs text-text-muted" role="status">
      <p className="font-medium text-conf-media">Sin pronóstico</p>
      {lista.length > 0
        ? <ul className="mt-1 list-disc pl-4">{lista.map((motivo) => <li key={motivo}>{motivo}</li>)}</ul>
        : <p className="mt-1">{detalle || "Faltan datos verificables para calcular una predicción responsable."}</p>}
      {referencia?.pct_local != null && (
        <p className="mt-2">
          <span className="text-text-dim">Referencia, no pronóstico ({referencia.nivel === "liga" ? "esta liga" : "promedio general"}): </span>
          Local <span className="num">{redondear(referencia.pct_local)}%</span> · Empate <span className="num">{redondear(referencia.pct_empate)}%</span> · Visitante <span className="num">{redondear(referencia.pct_visitante)}%</span>. No distingue a estos dos equipos.
        </p>
      )}
      <p className="mt-2 text-text-dim">Fuentes con datos: {fuentes?.length ? fuentes.join(", ") : "ninguna"}.</p>
    </div>
  );
}
