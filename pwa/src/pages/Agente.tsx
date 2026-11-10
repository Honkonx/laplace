import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "@/lib/AuthContext";
import * as api from "@/lib/api";

type Mensaje = { role: "user" | "assistant"; content: string; mode?: string };

export function Agente() {
  const { username } = useAuth();
  const [texto, setTexto] = useState("");
  const [usarIa, setUsarIa] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mensajes, setMensajes] = useState<Mensaje[]>([]);
  const [memoria, setMemoria] = useState<api.AgentMemory[]>([]);
  const [tareas, setTareas] = useState<api.AgentTask[]>([]);
  const [runs, setRuns] = useState<api.AgentRun[]>([]);
  const [herramientas, setHerramientas] = useState<api.AgentTool[]>([]);
  const [eventos, setEventos] = useState<api.AgentEvent[]>([]);
  const [conocimiento, setConocimiento] = useState<api.AgentKnowledge[]>([]);
  const [subagentes, setSubagentes] = useState<api.AgentSubagent[]>([]);
  const [propuestas, setPropuestas] = useState<api.AgentProposal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);

  useEffect(() => {
    if (!username) return;
    void Promise.all([api.listarMemoriaAgente(), api.listarTareasAgente(), api.listarRunsAgente(), api.listarHerramientasAgente(), api.listarEventosAgente()])
      .then(([memory, taskList, runList, toolList, eventList]) => {
        setMemoria(memory.memory);
        setTareas(taskList.tasks);
        setRuns(runList.runs);
        setHerramientas(toolList.tools);
        setEventos(eventList.events);
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "No se pudo cargar el agente"));
  }, [username]);

  useEffect(() => {
    if (!username) return;
    void Promise.all([api.listarConocimientoAgente(), api.listarSubagentesAgente(), api.listarPropuestasAgente()])
      .then(([knowledge, agents, proposals]) => {
        setConocimiento(knowledge.knowledge);
        setSubagentes(agents.subagents);
        setPropuestas(proposals.proposals);
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "No se pudo cargar conocimiento y subagentes"));
  }, [username]);

  async function enviar(event: FormEvent) {
    event.preventDefault();
    const mensaje = texto.trim();
    if (!mensaje || cargando) return;
    setTexto("");
    setError(null);
    setMensajes((items) => [...items, { role: "user", content: mensaje }]);
    setCargando(true);
    try {
      const respuesta = await api.conversarConAgente(mensaje, sessionId, usarIa);
      setSessionId(respuesta.session_id);
      setMensajes((items) => [...items, { role: "assistant", content: respuesta.respuesta, mode: respuesta.modo }]);
      const [taskList, runList] = await Promise.all([api.listarTareasAgente(), api.listarRunsAgente()]);
      setTareas(taskList.tasks);
      setRuns(runList.runs);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "No se pudo contactar al agente");
    } finally {
      setCargando(false);
    }
  }

  if (!username) {
    return <section className="space-y-3 pt-2"><h1 className="font-display text-2xl font-bold">Agente Laplace</h1><p className="text-sm text-text-muted">Inicia sesión para usar la memoria y el chat del agente.</p></section>;
  }

  return <section className="space-y-4 pt-2">
    <div><p className="font-mono text-xs uppercase tracking-widest text-accent">Control plane</p><h1 className="mt-1 font-display text-2xl font-bold">Laplace</h1><p className="mt-1 text-sm text-text-muted">Agente con reglas de alcance y memoria persistente.</p></div>
    <div className="rounded-2xl border border-border bg-surface p-3">
      <div className="min-h-64 space-y-2">{mensajes.length === 0 && <p className="p-2 text-sm text-text-muted">Pregunta sobre Laplace, fútbol, memoria o tareas.</p>}{mensajes.map((item, index) => <div key={index} className={`rounded-xl p-3 text-sm ${item.role === "user" ? "ml-6 bg-accent/20" : "mr-6 bg-surface-light"}`}><p className="mb-1 text-[10px] uppercase text-text-dim">{item.role === "user" ? "Tú" : `Laplace · ${item.mode ?? "reglas"}`}</p><p className="whitespace-pre-wrap">{item.content}</p></div>)}</div>
      {error && <p className="mt-2 rounded-lg bg-red-500/10 p-2 text-xs text-red-300">{error}</p>}
      <form onSubmit={enviar} className="mt-3 flex gap-2"><input value={texto} onChange={(event) => setTexto(event.target.value)} placeholder="Habla con Laplace..." className="min-w-0 flex-1 rounded-lg border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-accent" /><button disabled={cargando} className="rounded-lg bg-accent px-3 py-2 text-sm text-white disabled:opacity-50">{cargando ? "..." : "Enviar"}</button></form>
    </div>
    <label className="flex items-center gap-2 text-xs text-text-muted"><input type="checkbox" checked={usarIa} onChange={(event) => setUsarIa(event.target.checked)} /> Permitir IA en este turno</label>
    <div className="grid gap-3"><Panel titulo="Memoria" items={memoria.map((item) => `${item.scope} · ${item.topic_key}: ${item.content}`)} /><Panel titulo="Tareas y ejecuciones" items={[...tareas.map((item) => `${item.status} · ${item.kind}`), ...runs.map((item) => `${item.status} · ${item.agent}`)]} /><Panel titulo="Conocimiento" items={["Agente universal con alcance controlado", "Fútbol y apuestas como dominios activos", "Otros deportes como módulos futuros"]} /></div>
    <div className="grid gap-3"><Panel titulo="Herramientas" items={herramientas.map((item) => `${item.name} · ${item.risk}`)} /><Panel titulo="Eventos" items={eventos.map((item) => `${item.type} · ${item.created_at}`)} /></div>
    <div className="grid gap-3"><Panel titulo="Subagentes" items={subagentes.map((item) => `${item.name} · ${item.kind}`)} /><Panel titulo="Conocimiento sincronizado" items={conocimiento.map((item) => `${item.namespace}/${item.topic_key} · ${item.source}`)} /><Panel titulo="Aprendizaje controlado" items={propuestas.map((item) => `${item.topic_key} · ${item.scope} · ${item.status}`)} /></div>
  </section>;
}

function Panel({ titulo, items }: { titulo: string; items: string[] }) {
  return <div className="rounded-2xl border border-border bg-surface p-4"><h2 className="font-display font-bold">{titulo}</h2>{items.length === 0 ? <p className="mt-2 text-xs text-text-muted">Sin registros todavía.</p> : <ul className="mt-2 space-y-1">{items.slice(0, 10).map((item, index) => <li key={`${item}-${index}`} className="rounded-lg bg-surface-light p-2 text-xs text-text-muted">{item}</li>)}</ul>}</div>;
}
