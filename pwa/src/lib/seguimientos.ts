import { request } from "@/lib/api";

export type Estilo = "corto" | "normal" | "tecnico";

export const MERCADOS = ["1x2", "goles", "ambos marcan", "mas de 2,5"] as const;
export const MAX_MERCADOS = 4;

export interface ResumenSeguimientos {
  equipos: string[];
  ligas: string[];
  consentimiento: boolean;
  avisos: boolean;
  plan: string;
  limites: { equipos: number; ligas: number; partidos_24h: number };
  perfil: { zona_horaria: string | null; estilo: Estilo | null; mercados: string[] };
}

export interface RespuestaSeguimientos extends Partial<ResumenSeguimientos> {
  ok: boolean;
  mensaje: string;
}

const BASE = "/api/v1/agent";
const json = (cuerpo: unknown): RequestInit => ({ body: JSON.stringify(cuerpo) });

export const obtenerSeguimientos = () => request<ResumenSeguimientos>(`${BASE}/seguimientos`);
export const aceptarConsentimiento = () =>
  request<RespuestaSeguimientos>(`${BASE}/seguimientos/consentimiento`, { method: "POST" });
export const seguir = (tipo: "equipo" | "liga", nombre: string) =>
  request<RespuestaSeguimientos>(`${BASE}/seguimientos`, { method: "POST", ...json({ tipo, nombre }) });
export const dejarDeSeguir = (nombre: string) =>
  request<RespuestaSeguimientos>(`${BASE}/seguimientos?nombre=${encodeURIComponent(nombre)}`, { method: "DELETE" });
export const cambiarAvisos = (activar: boolean) =>
  request<RespuestaSeguimientos>(`${BASE}/seguimientos/avisos`, { method: "PUT", ...json({ activar }) });
export const guardarPerfil = (perfil: { zona_horaria?: string; estilo?: Estilo; mercados?: string[] }) =>
  request<RespuestaSeguimientos>(`${BASE}/perfil`, { method: "PUT", ...json(perfil) });
export const borrarPerfil = () => request<RespuestaSeguimientos>(`${BASE}/perfil`, { method: "DELETE" });
