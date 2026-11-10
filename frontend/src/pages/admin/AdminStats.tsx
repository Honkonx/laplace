import { obtenerStatsAdmin } from "@/lib/api";
import { useAdminData } from "@/lib/useAdminData";

// El backend (analisis_repo.leer_stats_aciertos) ya devuelve el winrate como porcentaje 0-100
// (round(aciertos/evaluados*100, 1)) — nunca como fracción, no hace falta normalizar acá.
function pct(v: number | null): string {
  return v == null ? "—" : `${v}%`;
}

export function AdminStats() {
  const { datos, cargando, error } = useAdminData(() => obtenerStatsAdmin(30));

  if (cargando) return <p className="text-text-muted">Cargando estadísticas…</p>;
  if (error) return <p className="text-conf-baja">{error}</p>;
  if (!datos) return null;

  const { pick_final: pf } = datos;
  const cards = [
    { etiqueta: "Winrate real (pick final)", valor: pct(pf.winrate) },
    { etiqueta: "Winrate confianza ALTA", valor: pct(pf.alta_winrate) },
    { etiqueta: "Winrate confianza MEDIA", valor: pct(pf.media_winrate) },
    { etiqueta: "Winrate consenso", valor: pct(pf.consenso_winrate) },
    { etiqueta: "Predicciones evaluadas", valor: pf.evaluados },
    { etiqueta: "Aciertos", valor: pf.aciertos },
  ];

  return (
    <div className="space-y-6">
      <p className="text-sm text-text-muted">
        Últimos {datos.periodo_dias} días (desde {datos.desde}) — números reales, no marketing:
        si el winrate es bajo, se muestra igual.
      </p>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((c) => (
          <div key={c.etiqueta} className="rounded-xl border border-border bg-surface p-4">
            <p className="text-xs text-text-muted">{c.etiqueta}</p>
            <p className="mt-1 num text-2xl font-medium text-text">{c.valor}</p>
          </div>
        ))}
      </div>

      <div>
        <h3 className="mb-2 text-sm font-medium text-text-muted">Winrate por fuente</h3>
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-4 py-3 font-medium">Fuente</th>
                <th className="px-4 py-3 font-medium">Total</th>
                <th className="px-4 py-3 font-medium">Evaluados</th>
                <th className="px-4 py-3 font-medium">Aciertos</th>
                <th className="px-4 py-3 font-medium">Winrate</th>
              </tr>
            </thead>
            <tbody>
              {datos.por_fuente.map((f) => (
                <tr key={f.fuente} className="border-b border-border last:border-0 hover:bg-surface">
                  <td className="px-4 py-2.5 font-medium">{f.fuente}</td>
                  <td className="px-4 py-2.5 text-text-muted">{f.total}</td>
                  <td className="px-4 py-2.5 text-text-muted">{f.evaluados}</td>
                  <td className="px-4 py-2.5 text-text-muted">{f.aciertos}</td>
                  <td className="px-4 py-2.5 text-accent">{pct(f.winrate)}</td>
                </tr>
              ))}
              {datos.por_fuente.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-text-muted">
                    Sin datos en el período.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
