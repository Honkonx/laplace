import { listarIntentosLoginAdmin } from "@/lib/api";
import { useAdminData } from "@/lib/useAdminData";

export function AdminIntentosLogin() {
  const { datos, cargando, error } = useAdminData(listarIntentosLoginAdmin);

  if (cargando) return <p className="text-text-muted">Cargando intentos de login…</p>;
  if (error) return <p className="text-conf-baja">{error}</p>;
  if (!datos) return null;

  return (
    <div className="space-y-3">
      <p className="max-w-xl text-sm text-text-muted">
        Intentos de login fallidos — útil para detectar patrones de fuerza bruta contra una
        cuenta. Nunca se guarda la clave intentada ni cuál de usuario/clave falló.
      </p>
      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-text-muted">
              <th className="px-4 py-3 font-medium">Usuario intentado</th>
              <th className="px-4 py-3 font-medium">Fecha</th>
            </tr>
          </thead>
          <tbody>
            {datos.intentos.map((i) => (
              <tr key={i.id} className="border-b border-border last:border-0 hover:bg-surface">
                <td className="px-4 py-2.5 font-medium">{i.username_intentado}</td>
                <td className="px-4 py-2.5 font-mono text-text-muted">{i.creado_en}</td>
              </tr>
            ))}
            {datos.intentos.length === 0 && (
              <tr>
                <td colSpan={2} className="px-4 py-6 text-center text-text-muted">
                  Sin intentos fallidos registrados.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
