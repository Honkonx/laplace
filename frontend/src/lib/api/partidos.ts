import { request } from "./cliente";

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

export interface WebFixture {
  /** El bot tiene modelo histórico para este partido (las cuotas reales también bastan al analizar). */
  pronosticable?: boolean;
  id: string; date: string; kickoff: string | null; status: string;
  score: { home: number | null; away: number | null };
  league: { id: string; name: string; logo: string | null };
  home: { name: string; logo: string | null };
  away: { name: string; logo: string | null };
}
export interface WebLeague { id: string; name: string; logo: string | null; count: number; priority: boolean; }
export async function obtenerCatalogoPartidos(params: { date: string; scope: "priority" | "all"; league?: string; q?: string }) {
  const query = new URLSearchParams({ date: params.date, scope: params.scope });
  if (params.league) query.set("league", params.league);
  if (params.q) query.set("q", params.q);
  return request<{ fixtures: WebFixture[]; leagues: WebLeague[]; total: number }>(`/api/v1/web/fixtures?${query.toString()}`);
}
export interface PrecisionUsuario { picks_consultados: number; sin_pronostico: number; verificados: number; aciertos: number; pendientes: number; acierto_pct: number | null; por_confianza: Record<string, { verificados: number; aciertos: number }>; muestra_minima: number; concluyente: boolean; nota: string; }
export async function obtenerPrecisionUsuario() { return request<PrecisionUsuario>("/api/v1/web/history/accuracy"); }
export async function obtenerHistorialWeb() { return request<{ total: number; items: Array<{ id: number; date: string; league: string | null; home: string | null; away: string | null; pick: string | null; confidence: string | null; created_at: string }> }>("/api/v1/web/history"); }
export interface PrediccionVarianteAgente { id: number; match_id: string | null; date: string; home: string; away: string; via: "ai_scout" | "bot"; pick: string | null; scoreline: string | null; confidence: string | null; provider: string | null; model: string | null; created_at: string; }
export async function obtenerPrediccionesAgente(matchId?: string) {
  const query = matchId ? `?match_id=${encodeURIComponent(matchId)}` : "";
  return request<{ items: PrediccionVarianteAgente[] }>(`/api/v1/web/agent-predictions${query}`);
}
export async function obtenerTrackRecord() { return request<{ volumen_real: { total?: number; evaluados?: number }; pick_final: { winrate?: number | null; muestra?: number }; brier_score: { valor?: number | null; muestra?: number }; rps: { rps_promedio: number | null; muestra: number; confiable: boolean; nota: string }; advertencia_general?: string }>("/api/v1/track-record"); }
