import type { AgentSession } from "@/lib/api";

function fechaRelativa(iso: string): string {
  const fecha = new Date(iso);
  if (Number.isNaN(fecha.getTime())) return "";
  const dias = Math.floor((Date.now() - fecha.getTime()) / 86_400_000);
  if (dias <= 0) return fecha.toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });
  if (dias === 1) return "Ayer";
  if (dias < 7) return fecha.toLocaleDateString("es-CL", { weekday: "short" });
  return fecha.toLocaleDateString("es-CL", { day: "numeric", month: "short" });
}

interface Props {
  sesiones: AgentSession[];
  activa: string | null;
  onAbrir: (id: string) => void;
  onNueva: () => void;
}

export function ListaSesiones({ sesiones, activa, onAbrir, onNueva }: Props) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border p-3">
        <h2 className="text-sm">Conversaciones</h2>
        <button type="button" onClick={onNueva} className="btn btn-sm btn-primary">Nueva</button>
      </div>
      <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto p-2">
        {sesiones.length === 0 && <li className="p-2 text-sm text-text-muted">Tus conversaciones quedarán guardadas aquí.</li>}
        {sesiones.map((s) => (
          <li key={s.id}>
            <button type="button" onClick={() => onAbrir(s.id)} aria-current={activa === s.id ? "true" : undefined}
              className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors ${activa === s.id ? "bg-surface-light text-text" : "text-text-muted hover:bg-surface-light hover:text-text"}`}>
              <span className="truncate">{s.title || "Conversación nueva"}</span>
              <span className="num shrink-0 text-[11px] text-text-dim">{fechaRelativa(s.updated_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
