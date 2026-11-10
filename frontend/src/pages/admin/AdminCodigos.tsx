import { listarCodigosAdmin } from "@/lib/api";
import { useAdminData } from "@/lib/useAdminData";

export function AdminCodigos() {
  const { datos, cargando, error } = useAdminData(listarCodigosAdmin);

  if (cargando) return <p className="text-text-muted">Cargando códigos…</p>;
  if (error) return <p className="text-conf-baja">{error}</p>;
  if (!datos) return null;

  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-text-muted">
            <th className="px-4 py-3 font-medium">Código</th>
            <th className="px-4 py-3 font-medium">Plan</th>
            <th className="px-4 py-3 font-medium">Días</th>
            <th className="px-4 py-3 font-medium">Usado</th>
            <th className="px-4 py-3 font-medium">Asignado a</th>
            <th className="px-4 py-3 font-medium">Usado por</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {datos.codigos.map((c) => (
            <tr key={c.codigo} className="border-b border-border last:border-0 hover:bg-surface">
              <td className="px-4 py-2.5">{c.codigo}</td>
              <td className="px-4 py-2.5 font-sans text-text-muted">{c.plan}</td>
              <td className="px-4 py-2.5 font-sans text-text-muted">{c.dias}</td>
              <td className="px-4 py-2.5">
                <span className={c.usado ? "text-conf-baja" : "text-conf-alta"}>
                  {c.usado ? "Sí" : "No"}
                </span>
              </td>
              <td className="px-4 py-2.5 text-text-muted">{c.device_id_asignado ?? "—"}</td>
              <td className="px-4 py-2.5 text-text-muted">{c.device_id_usado ?? "—"}</td>
            </tr>
          ))}
          {datos.codigos.length === 0 && (
            <tr>
              <td colSpan={6} className="px-4 py-6 text-center font-sans text-text-muted">
                Sin códigos.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
