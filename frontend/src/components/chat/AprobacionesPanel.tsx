import { useCallback, useEffect, useState } from "react";
import { decidirAprobacionAgente, listarAprobacionesAgente, type AgentApproval } from "@/lib/api";
import { describirError } from "@/lib/errores";
import { etiquetaHerramienta } from "@/lib/chat";

/** Solo admin. Aprobar ejecuta la herramienta (p. ej. publicar en Telegram), por eso pide una segunda confirmación. */
export function AprobacionesPanel() {
  const [pendientes, setPendientes] = useState<AgentApproval[] | null>(null);
  const [confirmando, setConfirmando] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(() => {
    listarAprobacionesAgente()
      .then((r) => setPendientes(r.approvals.filter((a) => a.status === "pending")))
      .catch((e: unknown) => setError(describirError(e).detalle));
  }, []);
  useEffect(cargar, [cargar]);

  async function decidir(id: string, aprobar: boolean) {
    setError(null);
    try {
      await decidirAprobacionAgente(id, aprobar);
      setConfirmando(null);
      cargar();
    } catch (e) {
      setError(describirError(e).detalle);
    }
  }

  return (
    <section aria-labelledby="titulo-aprobaciones">
      <h3 id="titulo-aprobaciones" className="text-sm">Aprobaciones pendientes</h3>
      {error && <p role="alert" className="mt-2 text-xs text-conf-baja">{error}</p>}
      {pendientes?.length === 0 && <p className="mt-2 text-xs text-text-muted">No hay acciones esperando tu decisión.</p>}
      <ul className="mt-2 space-y-2">
        {pendientes?.map((a) => (
          <li key={a.id} className="rounded-lg border border-border p-2.5 text-xs">
            <p className="font-medium text-text">{etiquetaHerramienta(a.tool)}</p>
            <p className="num mt-0.5 break-all text-text-dim">{JSON.stringify(a.payload).slice(0, 140)}</p>
            {confirmando === a.id ? (
              <div className="mt-2">
                <p className="text-text-muted">Esto ejecuta la acción de inmediato. ¿Confirmas?</p>
                <div className="mt-1.5 flex gap-2">
                  <button type="button" onClick={() => void decidir(a.id, true)} className="btn btn-sm btn-primary">Sí, aprobar</button>
                  <button type="button" onClick={() => setConfirmando(null)} className="btn btn-sm">Cancelar</button>
                </div>
              </div>
            ) : (
              <div className="mt-2 flex gap-2">
                <button type="button" onClick={() => setConfirmando(a.id)} className="btn btn-sm">Aprobar</button>
                <button type="button" onClick={() => void decidir(a.id, false)} className="btn btn-sm">Rechazar</button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
