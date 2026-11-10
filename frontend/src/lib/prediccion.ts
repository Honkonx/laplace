// Presentación pura de una predicción: toma lo que devuelve el backend y lo ordena para mostrarlo.
// No calcula probabilidades (eso es del motor, ver AGENTS.md §3): solo elige qué campos mostrar,
// redondea y traduce nombres de módulos.
import type { ResultadoPrediccion, TasaBaseLiga } from "./api";

export type NivelConfianza = "ALTA" | "MEDIA" | "BAJA";

export const MODULOS_ETIQUETA: Record<string, string> = {
  odds: "Cuotas del mercado (sin margen)",
  historico: "Dixon-Coles con histórico",
  forma: "Forma reciente",
  tabla: "Tabla de posiciones",
  poisson: "Poisson",
  h2h: "Enfrentamientos directos",
  bsd_ml: "Modelo ML externo",
};

export const CONFIANZA_DEFINICION: Record<NivelConfianza, string> = {
  ALTA: "Probabilidad ponderada del pick de 60% o más. En evaluación histórica ese tramo acertó cerca del 72%.",
  MEDIA: "Probabilidad ponderada del pick entre 50% y 60%. En evaluación histórica acertó cerca del 57%.",
  BAJA: "Probabilidad menor a 50%, o evidencia limitada (por ejemplo, un equipo sin historial). Poca ventaja sobre el azar: tómalo como una lectura, no como una señal.",
};

export interface Tripleta { local: number; empate: number; visitante: number }
export interface ModuloUsado { id: string; etiqueta: string; pesoPct: number; coincide: boolean; probs: Tripleta | null }
export interface VistaPrediccion {
  conPronostico: boolean;
  probs: Tripleta | null;
  /** "Local" | "Empate" | "Visitante" tal como lo emite el consenso */
  pick: string | null;
  confianza: NivelConfianza | null;
  modulos: ModuloUsado[];
  totalModulos: number;
  coinciden: number;
  desactualizadoDias: number | null;
  tasaBase: Tripleta | null;
  tasaBasePartidos: number | null;
  /** Por qué no hay pronóstico, cuando no lo hay */
  motivoSinPronostico: string | null;
}

function nivel(valor: string | undefined): NivelConfianza | null {
  return valor === "ALTA" || valor === "MEDIA" || valor === "BAJA" ? valor : null;
}

function tasaBase(t: TasaBaseLiga | null | undefined): Tripleta | null {
  if (!t || t.pct_local == null || t.pct_empate == null || t.pct_visitante == null) return null;
  return { local: t.pct_local / 100, empate: t.pct_empate / 100, visitante: t.pct_visitante / 100 };
}

export function construirVista(r: ResultadoPrediccion): VistaPrediccion {
  const c = r.consenso;
  const pick = c?.pick_final ?? null;
  const sinPick = !pick || pick.startsWith("Sin pronóstico") || !c.total_modulos;
  const pesos = c?.peso_efectivo ?? {};
  const aFavor = new Set(c?.modulos_en_consenso ?? []);
  const modulos = Object.entries(pesos)
    .filter(([, peso]) => peso > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([id, peso]) => {
      const m = r.modulos?.[id];
      const probs = m?.ok && m.prob_local != null && m.prob_empate != null && m.prob_visitante != null
        ? { local: m.prob_local, empate: m.prob_empate, visitante: m.prob_visitante }
        : null;
      return { id, etiqueta: MODULOS_ETIQUETA[id] ?? id, pesoPct: Math.round(peso * 100), coincide: aFavor.has(id), probs };
    });

  const historico = r.modulos?.historico;
  const desactualizado = historico?.ok && historico.modelo_desactualizado ? (historico.edad_modelo_dias ?? null) : null;

  const motivo = sinPick
    ? r.calidad_datos?.reason || c?.detalle || "Faltan datos verificables de ambos equipos para estimar este partido."
    : null;

  return {
    conPronostico: !sinPick && !!c.prob_ponderada,
    probs: !sinPick && c.prob_ponderada ? c.prob_ponderada : null,
    pick: sinPick ? null : pick,
    confianza: sinPick ? null : nivel(c.confianza_final),
    modulos,
    totalModulos: c?.total_modulos ?? 0,
    coinciden: c?.coinciden ?? 0,
    desactualizadoDias: desactualizado,
    tasaBase: tasaBase(r.tasa_base_liga),
    tasaBasePartidos: r.tasa_base_liga?.partidos ?? null,
    motivoSinPronostico: motivo,
  };
}

/** "Local" -> "River gana"; "Empate" -> "Empate". */
export function textoPick(pick: string, local: string, visitante: string): string {
  if (pick === "Local") return `${local} gana`;
  if (pick === "Visitante") return `${visitante} gana`;
  return pick;
}

export function pct(valor: number): number {
  return Math.round(valor * 100);
}
