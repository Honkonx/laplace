import { AGENT_URL, requestAt } from "./cliente";
import type { ResultadoPrediccion } from "./prediccion";

// ---- Agente Laplace ----

export interface AgentSession { id: string; title: string | null; channel: string; status: string; updated_at: string; }
export interface AgentMessage { role: "user" | "assistant"; content: string; mode: string; created_at: string; }
export interface AgentMemory { id?: number; scope: string; kind: string; topic_key: string; content: string; confidence: number; source: string; }
export interface AgentRun { id: string; agent: string; status: string; created_at: string; finished_at: string | null; output: Record<string, string | null>; }
// Contrato real de GET /api/v1/agent/tools (services/agent_tools.py::SportsTool).
export interface AgentTool { name: string; description: string; read_only: boolean; admin_only: boolean; requires_confirmation: boolean; }
export interface AgentApproval { id: string; invocation_id: string | null; user_id: string; tool: string; payload: Record<string, unknown>; status: string; requested_at: string; decided_at: string | null; }
export interface AgentEvent { id: number; user_id: string; task_id: string | null; run_id: string | null; type: string; payload: Record<string, unknown>; created_at: string; }
export interface AgentKnowledge { namespace: string; topic_key: string; content: string; source: string; }
export interface AgentSubagent { id: string; name: string; kind: string; capabilities: string[]; enabled: boolean; }
export interface AgentProposal { id: string; created_by: string; scope: string; topic_key: string; proposal: Record<string, unknown>; status: string; review_note: string | null; created_at: string; }

export interface RespuestaChatAgente {
  session_id: string;
  run_id: string;
  respuesta: string;
  modo: string;
  herramienta: string | null;
  /** Hoy el backend no la envía; si algún día devuelve el análisis estructurado, el chat lo dibuja. */
  prediccion?: ResultadoPrediccion;
}

export async function conversarConAgente(message: string, sessionId: string | null, usarIa: boolean) {
  return requestAt<RespuestaChatAgente>(AGENT_URL, "/api/v1/agent/chat", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId, channel: "web", usar_ia: usarIa }),
  });
}

export async function listarSesionesAgente() {
  return requestAt<{ sessions: AgentSession[] }>(AGENT_URL, "/api/v1/agent/sessions");
}

export async function obtenerMensajesSesionAgente(sessionId: string) {
  return requestAt<{ messages: AgentMessage[] }>(AGENT_URL, `/api/v1/agent/sessions/${encodeURIComponent(sessionId)}/messages`);
}

export async function listarMemoriaAgente() {
  return requestAt<{ memory: AgentMemory[] }>(AGENT_URL, "/api/v1/agent/memory");
}

export async function guardarMemoriaAgente(input: { scope?: "usuario" | "global"; kind: string; topic_key: string; content: string; confidence?: number; source?: string }) {
  return requestAt<{ id: number; saved: boolean }>(AGENT_URL, "/api/v1/agent/memory", { method: "POST", body: JSON.stringify(input) });
}

export async function listarConocimientoAgente() {
  return requestAt<{ knowledge: AgentKnowledge[] }>(AGENT_URL, "/api/v1/agent/knowledge");
}

export async function listarSubagentesAgente() {
  return requestAt<{ subagents: AgentSubagent[] }>(AGENT_URL, "/api/v1/agent/subagents");
}

export async function listarPropuestasAgente() {
  return requestAt<{ proposals: AgentProposal[] }>(AGENT_URL, "/api/v1/agent/learning/proposals");
}

export async function revisarPropuestaAgente(id: string, status: "approved" | "rejected", note?: string) {
  const query = new URLSearchParams({ status });
  if (note) query.set("note", note);
  return requestAt<{ id: string; status: string; applied: boolean }>(AGENT_URL, `/api/v1/agent/learning/proposals/${id}/review?${query.toString()}`, { method: "POST" });
}

export async function listarRunsAgente() {
  return requestAt<{ runs: AgentRun[] }>(AGENT_URL, "/api/v1/agent/runs");
}

export async function listarHerramientasAgente() {
  return requestAt<{ tools: AgentTool[] }>(AGENT_URL, "/api/v1/agent/tools");
}

export async function listarAprobacionesAgente() {
  return requestAt<{ approvals: AgentApproval[] }>(AGENT_URL, "/api/v1/agent/approvals");
}

export async function listarEventosAgente() {
  return requestAt<{ events: AgentEvent[] }>(AGENT_URL, "/api/v1/agent/events");
}

export async function decidirAprobacionAgente(id: string, aprobar: boolean) {
  return requestAt<{ id: string; status: string; executed: boolean }>(AGENT_URL, `/api/v1/agent/approvals/${id}/${aprobar ? "approve" : "reject"}`, { method: "POST" });
}

export interface AgentTask { id: string; parent_id: string | null; kind: string; status: string; cancel_requested?: boolean; created_at: string; started_at: string | null; finished_at: string | null; output: Record<string, unknown>; error: string | null; }
export async function listarTareasAgente() {
  return requestAt<{ tasks: AgentTask[] }>(AGENT_URL, "/api/v1/agent/tasks");
}

export async function listarSubagentes() {
  return listarSubagentesAgente();
}

export async function cancelarTareaAgente(taskId: string) {
  return requestAt<{ id: string; cancel_requested: boolean }>(AGENT_URL, `/api/v1/agent/tasks/${taskId}/cancel`, { method: "POST" });
}

// ---- Feedback, capacidades y cupo del agente ----

export async function enviarFeedbackAgente(input: { run_id: string; rating: 1 | 5; label: "util" | "no_util"; comment?: string }) {
  return requestAt<{ id: number; saved: boolean }>(AGENT_URL, "/api/v1/agent/feedback", { method: "POST", body: JSON.stringify(input) });
}

/** Forma tolerante: el endpoint lo agrega otro agente; todo campo es opcional y se valida al leerlo. */
export interface CapacidadesAgente {
  modos?: string[];
  herramientas?: Array<{ name: string; description?: string; admin_only?: boolean }>;
  rol?: string;
}
export interface UsoAgente {
  limite_dia?: number | null;
  usadas_hoy?: number | null;
  restantes?: number | null;
  limite_minuto?: number | null;
  ia_disponible?: boolean;
}
export async function obtenerCapacidadesAgente() {
  return requestAt<CapacidadesAgente>(AGENT_URL, "/api/v1/agent/capabilities");
}
export async function obtenerUsoAgente() {
  return requestAt<UsoAgente>(AGENT_URL, "/api/v1/agent/usage");
}
