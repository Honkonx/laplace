// Cliente HTTP al backend real de Laplace (FastAPI, backend/api/) — MISMO contrato que
// frontend/src/lib/api/ (web de escritorio). La PWA es una superficie nueva y separada, pero
// consume el mismo backend/API — nunca se inventó un endpoint nuevo acá. SPA pura, sin proxy
// server-side propio. Los endpoints de solo-lectura (partidos, predicción, simulador) no llevan
// ningún secreto — un secreto en JS del navegador es público por definición, así que nunca se
// usa `x-kairos-key` acá (eso es solo para la app móvil nativa compilada, app-android/). Lo que
// sí requiere identidad usa el JWT de `/api/v1/auth/login` vía el header Authorization.
//
// Nombre de la env var (VITE_KAIROS_BACKEND_URL, no VITE_LAPLACE_...): el backend real todavía
// usa nombres "Kairos" en su auth interna (header `x-kairos-key`, `KAIROS_AUTH_SECRET` en
// backend/api/core/config.py) — excepción protegida real, no una migración pendiente. Se
// mantiene el mismo nombre de variable que frontend/ para no crear una segunda convención.

const BASE_URL = import.meta.env.VITE_KAIROS_BACKEND_URL ?? "http://127.0.0.1:9001";
const AGENT_URL = import.meta.env.VITE_LAPLACE_AGENT_URL ?? "http://127.0.0.1:9100";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function obtenerToken(): string | null {
  return localStorage.getItem("laplace_token") ?? localStorage.getItem("laplace_web_token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = obtenerToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    let mensaje = `Error ${res.status}`;
    try {
      const body = await res.json();
      mensaje = body.detail ?? mensaje;
    } catch {
      // respuesta sin JSON — nos quedamos con el mensaje genérico
    }
    throw new ApiError(res.status, mensaje);
  }
  return res.json() as Promise<T>;
}

async function requestAt<T>(baseUrl: string, path: string, options: RequestInit = {}): Promise<T> {
  const token = obtenerToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${baseUrl}${path}`, { ...options, headers });
  if (!res.ok) {
    let mensaje = `Error ${res.status}`;
    try {
      const body = await res.json();
      mensaje = body.detail ?? mensaje;
    } catch {
      // respuesta sin JSON
    }
    throw new ApiError(res.status, mensaje);
  }
  return res.json() as Promise<T>;
}

// ---- Partidos ----

export interface Equipo {
  Nm: string;
  Img?: string;
}

export interface EventoPartido {
  Eid: string;
  Eps: string; // "NS" = no iniciado
  T1: Equipo[];
  T2: Equipo[];
  Esd?: string | number;
}

export interface Liga {
  Snm?: string;
  CompN?: string;
  Events: EventoPartido[];
}

export async function obtenerPartidos(fechaYyyymmdd: string) {
  return request<{ ok: boolean; fuente: string; total: number; Stages: Liga[] }>(
    `/api/v1/partidos?fecha=${fechaYyyymmdd}`,
  );
}

export interface WebLeague { id: string; name: string; logo: string | null; count: number; priority: boolean; }
export interface WebFixture { pronosticable?: boolean; id: string; date: string; kickoff: string | null; status: string; league: { id: string; name: string; logo: string | null }; home: { name: string; logo: string | null }; away: { name: string; logo: string | null }; }
export async function obtenerCatalogoPartidos(params: { date: string; scope: "priority" | "all"; league?: string; q?: string }) {
  const qs = new URLSearchParams({ date: params.date, scope: params.scope });
  if (params.league) qs.set("league", params.league); if (params.q) qs.set("q", params.q);
  return request<{ date: string; scope: string; total: number; fixtures: WebFixture[]; leagues: WebLeague[] }>(`/api/v1/web/fixtures?${qs}`);
}

// ---- Predicción ----

export interface ModuloResultado {
  ok: boolean;
  pick: string;
  prob_local: number;
  prob_empate: number;
  prob_visitante: number;
  confianza_score: number;
  confianza: string;
  score_para_claude?: string;
  marcador_probable?: string;
  over25_prob?: number;
  btts_prob?: number;
}

export interface ConsensoResultado {
  pick_final: string;
  nivel: string;
  score_consenso: number;
  confianza_final: string;
  detalle: string;
  total_modulos: number;
  coinciden: number;
  prob_ponderada?: { local: number; empate: number; visitante: number };
  peso_efectivo?: Record<string, number>;
  modulos_en_consenso?: string[];
  modulos_disidentes?: string[];
}

export interface TasaBaseLiga {
  /** "liga": frecuencias de esa liga; "general": promedio de todas las ligas con histórico. */
  nivel?: "liga" | "general";
  pct_local?: number | null;
  pct_empate?: number | null;
  pct_visitante?: number | null;
  partidos?: number | null;
}

export interface ResultadoPrediccion {
  partido_id: string;
  local: string;
  visitante: string;
  liga: string;
  modulos: Record<string, ModuloResultado | null>;
  modulos_skip: Record<string, string>;
  consenso: ConsensoResultado;
  standings_info?: string;
  odds_info?: string;
  h2h_resumen?: string;
  calidad_datos?: { eligible: boolean; tier?: string; sources?: string[]; source_count?: number; reason?: string | null };
  motivos_sin_pronostico?: string[];
  referencia_tasa_base?: TasaBaseLiga | null;
}

export async function pedirPrediccion(partido: {
  match_id: string;
  local: string;
  visitante: string;
  liga: string;
  fecha: string;
}) {
  return request<ResultadoPrediccion>("/api/v1/prediccion-web", {
    method: "POST",
    body: JSON.stringify(partido),
  });
}

// ---- Simulador de liga ----

export interface ResultadoSimulador {
  ok: boolean;
  razon?: string;
  liga_slug?: string;
  liga_nombre?: string;
  n_simulaciones?: number;
  partidos_pendientes?: number;
  tabla?: Record<
    string,
    { prob_campeon: number; prob_copa: number; prob_descenso: number; posicion_promedio: number }
  >;
}

export async function simularLiga(ligaSlug: string) {
  return request<ResultadoSimulador>(`/api/v1/simulador/${ligaSlug}`);
}

// ---- Auth ----

export interface SesionUsuario {
  token: string;
  username: string;
  plan: string;
}

export async function registrarse(username: string, password: string, termsAccepted = true) {
  // origen: el backend valida contra ORIGENES_VALIDOS = {"app", "web"} (backend/api/routers/
  // auth.py) — no existe un tercer valor "pwa"; un registro real con "pwa" devolvería 400. La
  // PWA es una superficie web (browser, JWT vía Authorization), así que usa "web" — mismo
  // origen que frontend/, no se infló el contrato del backend por esto.
  return request<SesionUsuario>("/api/v1/auth/registro", {
    method: "POST",
    body: JSON.stringify({
      username,
      password,
      origen: "web",
      terms_accepted: termsAccepted,
      terms_version: "2026-09-25",
    }),
  });
}

export async function iniciarSesion(username: string, password: string) {
  return request<SesionUsuario>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function cerrarSesion() {
  return request<{ revocado: boolean }>("/api/v1/auth/logout", { method: "POST" });
}

export async function quienSoy() {
  return request<{ username: string; plan: string; device_id: string; activo_hasta?: string | null }>("/api/v1/auth/me");
}

export interface RespuestaActivarCodigo {
  activado: boolean;
  plan: string;
  rol: string;
  dias: number;
  activo_hasta: string;
  mensaje: string;
  token: string;
}

export async function activarCodigoWeb(codigo: string) {
  return request<RespuestaActivarCodigo>("/api/v1/auth/activar-codigo", {
    method: "POST",
    body: JSON.stringify({ codigo }),
  });
}

// ---- Agente Laplace ----

export interface AgentMemory { scope: string; kind: string; topic_key: string; content: string; confidence: number; source: string; }
export interface AgentTask { id: string; kind: string; status: string; cancel_requested?: boolean; created_at: string; output: Record<string, unknown>; error: string | null; }
export interface AgentRun { id: string; agent: string; status: string; created_at: string; output: Record<string, string | null>; }
export interface AgentTool { name: string; description: string; risk: string; requires_admin: boolean; requires_confirmation: boolean; }
export interface AgentEvent { id: number; type: string; task_id: string | null; created_at: string; }
export interface AgentKnowledge { namespace: string; topic_key: string; content: string; source: string; }
export interface AgentSubagent { id: string; name: string; kind: string; capabilities: string[]; enabled: boolean; }
export interface AgentProposal { id: string; scope: string; topic_key: string; status: string; }

export async function conversarConAgente(message: string, sessionId: string | null, usarIa: boolean) {
  return requestAt<{ session_id: string; run_id: string; respuesta: string; modo: string; herramienta: string | null }>(AGENT_URL, "/api/v1/agent/chat", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId, channel: "pwa", usar_ia: usarIa }),
  });
}

export async function listarMemoriaAgente() {
  return requestAt<{ memory: AgentMemory[] }>(AGENT_URL, "/api/v1/agent/memory");
}

export async function listarTareasAgente() {
  return requestAt<{ tasks: AgentTask[] }>(AGENT_URL, "/api/v1/agent/tasks");
}

export async function listarRunsAgente() {
  return requestAt<{ runs: AgentRun[] }>(AGENT_URL, "/api/v1/agent/runs");
}

export async function listarHerramientasAgente() {
  return requestAt<{ tools: AgentTool[] }>(AGENT_URL, "/api/v1/agent/tools");
}

export async function listarEventosAgente() {
  return requestAt<{ events: AgentEvent[] }>(AGENT_URL, "/api/v1/agent/events");
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
