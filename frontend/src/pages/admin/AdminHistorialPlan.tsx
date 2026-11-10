import { listarHistorialPlanAdmin } from "@/lib/api";
import { useAdminData } from "@/lib/useAdminData";

export function AdminHistorialPlan() {
  const { datos, cargando, error } = useAdminData(listarHistorialPlanAdmin);

  if (cargando) return <p className="text-text-muted">Cargando historial…</p>;
  if (error) return <p className="text-conf-baja">{error}</p>;
  if (!datos) return null;

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-muted">
            <th className="px-4 py-3 font-medium">Device ID</th>
            <th className="px-4 py-3 font-medium">Plan anterior</th>
            <th className="px-4 py-3 font-medium">Plan nuevo</th>
            <th className="px-4 py-3 font-medium">Medio</th>
            <th className="px-4 py-3 font-medium">Fecha</th>
          </tr>
        </thead>
        <tbody>
          {datos.historial.map((h) => (
            <tr key={h.id} className="border-b border-border last:border-0 hover:bg-surface">
              <td className="px-4 py-2.5 font-mono text-xs">{h.device_id}</td>
              <td className="px-4 py-2.5 text-text-muted">{h.plan_anterior ?? "—"}</td>
              <td className="px-4 py-2.5 text-accent">{h.plan_nuevo}</td>
              <td className="px-4 py-2.5 text-text-muted">{h.medio}</td>
              <td className="px-4 py-2.5 font-mono text-text-muted">{h.creado_en}</td>
            </tr>
          ))}
          {datos.historial.length === 0 && (
            <tr>
              <td colSpan={5} className="px-4 py-6 text-center text-text-muted">
                Sin cambios de plan registrados.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
