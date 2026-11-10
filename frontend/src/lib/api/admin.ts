import { request } from "./cliente";

// ---- Admin (solo lectura, v1 — ver PROPUESTA_DASHBOARD_ADMIN.md) ----
// Contrato REAL confirmado leyendo backend/api/routers/admin.py + los repos que arma cada
// respuesta (usuarios_repo.listar_usuarios, auditoria_repo.listar_historial_plan/
// listar_intentos_login_fallidos, jobs_repo.listar_jobs, codigos_repo.listar_codigos,
// analisis_repo.leer_stats_aciertos) — 2026-09-09, reemplaza el contrato asumido a mano que
// tenía esta ronda antes de integrar los dos lados en paralelo.

export interface UsuarioAdmin {
  id: number;
  device_id: string;
  username: string | null; // null para usuarios de Telegram/app sin login por usuario+clave
  activo: boolean;
  plan: string;
  origen: string;
  nickname: string | null;
  activo_hasta: string | null;
  creado_en: string;
}

export interface ListaUsuariosAdmin {
  total: number;
  limit: number;
  offset: number;
  usuarios: UsuarioAdmin[];
}

export async function listarUsuariosAdmin(
  params: { limit?: number; offset?: number; q?: string } = {},
) {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  if (params.q) qs.set("q", params.q);
  const query = qs.toString();
  return request<ListaUsuariosAdmin>(`/api/v1/admin/usuarios${query ? `?${query}` : ""}`);
}

export interface CodigoAccesoAdmin {
  codigo: string;
  plan: string;
  dias: number;
  usado: boolean;
  device_id_asignado: string | null; // reservado para este device (aún no canjeado)
  device_id_usado: string | null; // quién lo canjeó realmente
  creado_en: string;
  usado_en: string | null;
}

export async function listarCodigosAdmin(filtro: "disponibles" | "usados" | "todos" = "todos") {
  return request<{ filtro: string; total: number; codigos: CodigoAccesoAdmin[] }>(
    `/api/v1/admin/codigos?filtro=${filtro}`,
  );
}

export interface HistorialPlanAdmin {
  id: number;
  device_id: string; // no hay username — un usuario de Telegram no tiene uno
  plan_anterior: string | null;
  plan_nuevo: string;
  medio: "codigo" | "admin";
  detalle: string | null;
  creado_en: string;
}

export async function listarHistorialPlanAdmin(params: { limit?: number; offset?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return request<{ total: number; limit: number; offset: number; historial: HistorialPlanAdmin[] }>(
    `/api/v1/admin/historial-plan${query ? `?${query}` : ""}`,
  );
}

export interface IntentoLoginFallidoAdmin {
  id: number;
  username_intentado: string;
  creado_en: string; // nunca se guarda IP ni motivo — el login no revela si falló usuario o clave
}

export async function listarIntentosLoginAdmin(params: { limit?: number; offset?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return request<{ total: number; limit: number; offset: number; intentos: IntentoLoginFallidoAdmin[] }>(
    `/api/v1/admin/intentos-login${query ? `?${query}` : ""}`,
  );
}

export interface JobAdmin {
  job_id: string;
  match_id: string;
  fecha_partido: string;
  origen: string;
  status: string;
  intentos: number;
  plan: string;
  device_id_app: string | null;
  creado_en: string;
  completado_en: string | null;
}

export async function listarJobsAdmin(params: { status?: string; limit?: number; offset?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.status) qs.set("status", params.status);
  if (params.limit != null) qs.set("limit", String(params.limit));
  if (params.offset != null) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return request<{ total: number; limit: number; offset: number; jobs: JobAdmin[] }>(
    `/api/v1/admin/jobs${query ? `?${query}` : ""}`,
  );
}

export interface StatsPorFuenteAdmin {
  fuente: string;
  total: number;
  evaluados: number;
  aciertos: number;
  winrate: number | null; // porcentaje 0-100, null si no hay evaluados todavía
}

export interface StatsAdmin {
  periodo_dias: number;
  desde: string;
  por_fuente: StatsPorFuenteAdmin[];
  pick_final: {
    total: number;
    evaluados: number;
    aciertos: number;
    winrate: number | null;
    alta_winrate: number | null;
    media_winrate: number | null;
    consenso_winrate: number | null;
  };
}

export async function obtenerStatsAdmin(dias = 30) {
  return request<StatsAdmin>(`/api/v1/admin/stats?dias=${dias}`);
}

export interface ProveedorIaAdmin { id: string; configurado: boolean; modelo: string; modelos_sugeridos?: string[]; cloud_only?: boolean; }
export async function obtenerProveedoresIaAdmin() {
  return request<{ agent_ia_activa: boolean; proveedores: ProveedorIaAdmin[]; configuracion: string }>("/api/v1/admin/ia/proveedores");
}
export async function configurarProveedorIaAdmin(provider: string, apiKey: string, model: string) {
  return request<{ provider: string; model: string; restart_required: boolean; message: string }>("/api/v1/admin/ia/proveedores", { method: "POST", body: JSON.stringify({ provider, api_key: apiKey, model }) });
}

// ---- Conexiones externas (solo admin): una lista para datos, IA y Telegram ----

export interface ConexionAdmin {
  id: string; numero: number; grupo: string; nombre: string; variable: string; sirve: string; plan: string; enlace: string; host: string;
  configurada: boolean; destacada: boolean; cobra_por_llamada: boolean; cuesta: string | null;
}
export interface ConexionesAdmin {
  grupos: { id: string; titulo: string; nota: string }[]; conexiones: ConexionAdmin[]; faltantes: string[]; orden_ia: string[]; nota: string;
}
export interface ResultadoPruebaConexion { id: string; estado: "ok" | "bad" | "warn"; detalle: string; http?: number | null; requiere_confirmacion: boolean; coste?: string }
export async function obtenerConexionesAdmin() {
  return request<ConexionesAdmin>("/api/v1/admin/conexiones");
}
export async function probarConexionAdmin(id: string, confirmarCoste = false) {
  return request<ResultadoPruebaConexion>(`/api/v1/admin/conexiones/${encodeURIComponent(id)}/probar?confirmar_coste=${confirmarCoste}`, { method: "POST" });
}
export async function guardarConexionAdmin(id: string, clave: string, confirmarCoste = false) {
  return request<{ id: string; estado: string | null; detalle: string; message: string }>(`/api/v1/admin/conexiones/${encodeURIComponent(id)}`, {
    method: "POST", body: JSON.stringify({ clave, probar_antes: true, confirmar_coste: confirmarCoste }),
  });
}
export async function borrarConexionAdmin(id: string) {
  return request<{ id: string; message: string }>(`/api/v1/admin/conexiones/${encodeURIComponent(id)}`, { method: "DELETE" });
}
export async function guardarOrdenIaAdmin(orden: string[]) {
  return request<{ orden: string[]; message: string }>("/api/v1/admin/conexiones-orden-ia", { method: "PUT", body: JSON.stringify({ orden }) });
}

// ---- Salud (solo admin) ----

export interface FuenteDeportiva { id: string; configured: boolean; role: string; healthy: boolean | null; status_http: number | null; latency_ms: number | null; quota_remaining: string | null; detail: string | null; last_verified: string | null; }
export async function obtenerFuentesDeportivas() {
  return request<{ sources: FuenteDeportiva[]; note: string }>("/api/v1/admin/sports/fuentes");
}
export interface JobScheduler { ultimo_exitoso_en: string | null; ultima_corrida_en: string | null; ultima_corrida_ok: boolean | null; estado: string; atrasado: boolean; edad_minutos: number | null; ventana_minutos: number; }
export async function obtenerEstadoScheduler() {
  return request<{ scheduler_corriendo: boolean; saludable: boolean; jobs: Record<string, JobScheduler> }>("/api/v1/scheduler/status");
}
