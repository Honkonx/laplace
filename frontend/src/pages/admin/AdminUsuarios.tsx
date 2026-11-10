import { useState } from "react";
import { listarUsuariosAdmin } from "@/lib/api";
import { useAdminData } from "@/lib/useAdminData";

const LIMITE = 20;

export function AdminUsuarios() {
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const { datos, cargando, error } = useAdminData(
    () => listarUsuariosAdmin({ limit: LIMITE, offset, q: q || undefined }),
    [q, offset],
  );

  return (
    <div className="space-y-4">
      <input
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOffset(0);
        }}
        placeholder="Buscar por usuario…"
        className="w-full max-w-xs rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text outline-none focus:border-accent"
      />

      {cargando && <p className="text-text-muted">Cargando usuarios…</p>}
      {error && <p className="text-conf-baja">{error}</p>}

      {datos && (
        <>
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-text-muted">
                  <th className="px-4 py-3 font-medium">Usuario</th>
                  <th className="px-4 py-3 font-medium">Plan</th>
                  <th className="px-4 py-3 font-medium">Activo</th>
                  <th className="px-4 py-3 font-medium">Creado</th>
                </tr>
              </thead>
              <tbody>
                {datos.usuarios.map((u) => (
                  <tr key={u.id} className="border-b border-border last:border-0 hover:bg-surface">
                    <td className="px-4 py-2.5 font-medium">{u.username}</td>
                    <td className="px-4 py-2.5 text-text-muted">{u.plan}</td>
                    <td className="px-4 py-2.5">
                      <span className={u.activo ? "text-conf-alta" : "text-conf-baja"}>
                        {u.activo ? "Sí" : "No"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-text-muted">{u.creado_en}</td>
                  </tr>
                ))}
                {datos.usuarios.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-text-muted">
                      Sin resultados.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between text-sm text-text-muted">
            <span>{datos.total} usuarios en total</span>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - LIMITE))}
                disabled={offset === 0}
                className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40"
              >
                Anterior
              </button>
              <button
                onClick={() => setOffset(offset + LIMITE)}
                disabled={offset + LIMITE >= datos.total}
                className="rounded-lg border border-border px-3 py-1.5 disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
