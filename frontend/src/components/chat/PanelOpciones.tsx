import { useEffect, useState, type ReactNode } from "react";
import { listarConocimientoAgente, listarHerramientasAgente, listarMemoriaAgente, type AgentKnowledge, type AgentMemory, type AgentTool, type PrediccionVarianteAgente, type UsoAgente } from "@/lib/api";
import { etiquetaHerramienta } from "@/lib/chat";
import { AprobacionesPanel } from "./AprobacionesPanel";

interface Props {
  usarIa: boolean;
  onUsarIa: (valor: boolean) => void;
  esAdmin: boolean;
  uso: UsoAgente | null;
  usoDisponible: boolean;
  variantes: PrediccionVarianteAgente[];
}

function Seccion({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <section className="border-b border-border px-4 py-4 last:border-0">
      <h3 className="mb-2 text-sm">{titulo}</h3>
      {children}
    </section>
  );
}

function CupoIa({ uso }: { uso: UsoAgente }) {
  const limite = uso.limite_dia ?? null;
  const restantes = uso.restantes ?? (limite != null && uso.usadas_hoy != null ? Math.max(0, limite - uso.usadas_hoy) : null);
  if (restantes == null) return <p className="text-xs text-text-muted">El servidor no informó tu cupo todavía.</p>;
  const agotado = restantes <= 0;
  const porcentaje = limite ? Math.round(((limite - restantes) / limite) * 100) : 0;
  return (
    <div>
      <p className="text-sm">
        <span className={`num font-medium ${agotado ? "text-conf-baja" : ""}`}>{restantes}</span>
        {limite != null && <span className="num text-text-muted"> de {limite}</span>}
        <span className="text-text-muted"> respuestas con IA hoy</span>
      </p>
      {limite != null && (
        <div role="meter" aria-valuemin={0} aria-valuemax={limite} aria-valuenow={restantes} aria-label="Cupo de IA restante" className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-light">
          <div className={`h-full ${agotado ? "bg-conf-baja" : "bg-accent"}`} style={{ width: `${100 - porcentaje}%` }} />
        </div>
      )}
      {agotado && <p className="mt-1.5 text-xs text-text-muted">Sigues pudiendo preguntar: las respuestas por reglas no gastan cupo.</p>}
    </div>
  );
}

export function PanelOpciones({ usarIa, onUsarIa, esAdmin, uso, usoDisponible, variantes }: Props) {
  const [herramientas, setHerramientas] = useState<AgentTool[] | null>(null);
  const [memoria, setMemoria] = useState<AgentMemory[] | null>(null);
  const [conocimiento, setConocimiento] = useState<AgentKnowledge[] | null>(null);

  useEffect(() => {
    listarHerramientasAgente().then((r) => setHerramientas(r.tools)).catch(() => setHerramientas([]));
    listarMemoriaAgente().then((r) => setMemoria(r.memory)).catch(() => setMemoria([]));
    listarConocimientoAgente().then((r) => setConocimiento(r.knowledge)).catch(() => setConocimiento([]));
  }, []);

  const sinCupo = usoDisponible && uso != null && (uso.restantes ?? 1) <= 0;
  const iaNoDisponible = (usoDisponible && uso?.ia_disponible === false) || sinCupo;
  const visibles = (herramientas ?? []).filter((t) => esAdmin || !t.admin_only);
  const espacios = [...new Set((conocimiento ?? []).map((k) => k.namespace))];

  return (
    <div className="h-full overflow-y-auto">
      <Seccion titulo="Modo de respuesta">
        <div role="radiogroup" aria-label="Modo de respuesta" className="grid gap-2">
          {[
            { valor: false, titulo: "Por reglas", texto: "Respuestas directas con datos verificados del bot. No gasta cupo." },
            { valor: true, titulo: "Con IA", texto: "Redacta en lenguaje natural. Las cifras siguen saliendo del motor." },
          ].map((m) => {
            const deshabilitado = m.valor && iaNoDisponible;
            const activo = usarIa === m.valor && !deshabilitado;
            return (
              <button key={m.titulo} type="button" role="radio" aria-checked={activo} disabled={deshabilitado} onClick={() => onUsarIa(m.valor)}
                className={`min-h-11 rounded-lg border p-2.5 text-left transition-colors disabled:opacity-50 ${activo ? "border-accent bg-surface-light" : "border-border hover:bg-surface-light"}`}>
                <span className="block text-sm font-medium">{m.titulo}</span>
                <span className="block text-xs text-text-muted">{deshabilitado ? "No disponible ahora: sin cupo o sin proveedor configurado." : m.texto}</span>
              </button>
            );
          })}
        </div>
      </Seccion>

      <Seccion titulo="Cupo de IA">
        {usoDisponible && uso ? <CupoIa uso={uso} /> : <p className="text-xs text-text-muted">No se pudo consultar el cupo en este momento.</p>}
      </Seccion>

      <Seccion titulo="Contexto que usa Laplace">
        <p className="text-xs text-text-muted">
          Memoria personal: <span className="num text-text">{memoria?.length ?? "…"}</span> {memoria?.length === 1 ? "dato" : "datos"}. Conocimiento: <span className="num text-text">{conocimiento?.length ?? "…"}</span> entradas{espacios.length ? ` (${espacios.join(", ")})` : ""}.
        </p>
        {memoria && memoria.length > 0 && (
          <details className="mt-2 text-xs">
            <summary className="cursor-pointer py-1 text-text-muted hover:text-text">Ver mi memoria</summary>
            <ul className="mt-1 space-y-1.5">
              {memoria.slice(0, 8).map((m, i) => <li key={m.id ?? i}><span className="text-text-dim">{m.topic_key}:</span> {m.content}</li>)}
            </ul>
          </details>
        )}
      </Seccion>

      <Seccion titulo={esAdmin ? "Herramientas (administrador)" : "Herramientas disponibles"}>
        {herramientas == null ? <p className="text-xs text-text-muted">Cargando…</p> : (
          <ul className="space-y-2">
            {visibles.map((t) => (
              <li key={t.name} className="text-xs">
                <p className="font-medium text-text">{etiquetaHerramienta(t.name)}{t.admin_only && <span className="chip ml-1.5">solo admin</span>}</p>
                <p className="text-text-muted">{t.description}</p>
              </li>
            ))}
            {visibles.length === 0 && <li className="text-xs text-text-muted">No se pudo leer el catálogo de herramientas.</li>}
          </ul>
        )}
      </Seccion>

      {esAdmin && <Seccion titulo="Administración"><AprobacionesPanel /></Seccion>}

      <Seccion titulo="Tus hipótesis solo IA">
        {variantes.length === 0 ? <p className="text-xs text-text-muted">Aún no guardaste ninguna. Son experimentales y no reemplazan al análisis del bot.</p> : (
          <ul className="space-y-1.5">
            {variantes.slice(0, 3).map((v) => (
              <li key={v.id} className="text-xs"><span className="font-medium">{v.home} vs {v.away}</span><br /><span className="text-text-muted">{v.pick || "Sin pick"}{v.scoreline ? ` · ${v.scoreline}` : ""} · experimental</span></li>
            ))}
          </ul>
        )}
      </Seccion>
    </div>
  );
}
