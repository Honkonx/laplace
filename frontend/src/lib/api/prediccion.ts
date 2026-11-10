import { request } from "./cliente";

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
  /** Solo el módulo `historico`: ratings Dixon-Coles con más de un año de antigüedad. */
  modelo_desactualizado?: boolean;
  edad_modelo_dias?: number | null;
  metodo?: string;
}

export interface ConsensoResultado {
  pick_final: string;
  nivel: string;
  score_consenso: number;
  confianza_final: string;
  detalle: string;
  total_modulos: number;
  coinciden: number;
  /** Probabilidad ponderada del consenso: la que realmente decide el pick público. */
  prob_ponderada?: { local: number; empate: number; visitante: number };
  /** Peso efectivo (fracción 0-1) de cada módulo en el consenso. */
  peso_efectivo?: Record<string, number>;
  modulos_en_consenso?: string[];
  modulos_disidentes?: string[];
}

export interface TasaBaseLiga {
  /** "liga": frecuencias de esa liga; "general": promedio de todas las ligas con histórico (la liga no está cubierta). */
  nivel?: "liga" | "general";
  pct_local?: number | null;
  pct_empate?: number | null;
  pct_visitante?: number | null;
  partidos?: number | null;
  temporadas?: string[] | null;
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
  /** Aún no lo envía /prediccion-web; la tarjeta lo muestra solo si llega. */
  tasa_base_liga?: TasaBaseLiga | null;
  /** Con "Sin pronóstico": por qué no hay estimación propia y la frecuencia histórica como REFERENCIA, no como pick. */
  /** En qué se apoya el pronóstico: N4 histórico+cuotas, N3 cuotas, N2 histórico, N1 equipo nuevo, N0 sin pronóstico, DEBIL. */
  nivel_evidencia?: { codigo: string; etiqueta: string };
  motivos_sin_pronostico?: string[];
  referencia_tasa_base?: TasaBaseLiga | null;
  calidad_datos?: { eligible: boolean; tier?: string; sources?: string[]; source_count?: number; reason?: string | null };
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
