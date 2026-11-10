import { useState } from "react";
import { listarJobsAdmin } from "@/lib/api";
import { useAdminData } from "@/lib/useAdminData";

export function AdminJobs() {
  const [status, setStatus] = useState("");
  const { datos, cargando, error } = useAdminData(
    () => listarJobsAdmin(status ? { status } : {}),
    [status],
  );

  return (
    <div className="space-y-4">
      <input
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        placeholder="Filtrar por status (ej. pendiente, listo, error)…"
        className="w-full max-w-sm rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-accent"
      />

      {cargando && <p className="text-text-muted">Cargando jobs…</p>}
      {error && <p className="text-conf-baja">{error}</p>}

      {datos && (
        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-text-muted">
                <th className="px-4 py-3 font-medium">Job ID</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Partido</th>
                <th className="px-4 py-3 font-medium">Origen</th>
                <th className="px-4 py-3 font-medium">Plan</th>
                <th className="px-4 py-3 font-medium">Intentos</th>
                <th className="px-4 py-3 font-medium">Creado</th>
                <th className="px-4 py-3 font-medium">Completado</th>
              </tr>
            </thead>
            <tbody>
              {datos.jobs.map((j) => (
                <tr key={j.job_id} className="border-b border-border last:border-0 hover:bg-surface">
                  <td className="px-4 py-2.5 font-mono text-xs text-text-muted">{j.job_id}</td>
                  <td className="px-4 py-2.5">{j.status}</td>
                  <td className="px-4 py-2.5 text-text-muted">
                    {j.match_id} · {j.fecha_partido}
                  </td>
                  <td className="px-4 py-2.5 text-text-muted">{j.origen}</td>
                  <td className="px-4 py-2.5 text-text-muted">{j.plan}</td>
                  <td className="px-4 py-2.5 text-text-muted">{j.intentos}</td>
                  <td className="px-4 py-2.5 font-mono text-text-muted">{j.creado_en ?? "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-text-muted">{j.completado_en ?? "—"}</td>
                </tr>
              ))}
              {datos.jobs.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-6 text-center text-text-muted">
                    Sin jobs.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
