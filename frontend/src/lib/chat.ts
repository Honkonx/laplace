import type { ResultadoPrediccion } from "./api";

export interface MensajeUI {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** Campo `modo` del backend: "reglas", "ia · proveedor/modelo", "reglas_fallback"… */
  modo?: string;
  herramienta?: string | null;
  /** Solo en respuestas de esta sesión: sin run_id no se puede enviar valoración. */
  runId?: string;
  prediccion?: ResultadoPrediccion;
  creado: string;
}

export interface FuenteRespuesta {
  /** "reglas" o "ia" decide el color del chip; el texto siempre dice la fuente. */
  tipo: "reglas" | "ia" | "politica";
  etiqueta: string;
  detalle?: string;
}

/** Traduce el `modo` del backend a una etiqueta honesta de dónde salió la respuesta. */
export function fuenteDeModo(modo: string | undefined): FuenteRespuesta | null {
  if (!modo || modo === "entrada") return null;
  if (modo === "politica") return { tipo: "politica", etiqueta: "Política de uso" };
  if (modo === "reglas_fallback") return { tipo: "reglas", etiqueta: "Por reglas", detalle: "La IA no estaba disponible; respondió el motor de reglas." };
  if (modo.startsWith("ia_experimental")) return { tipo: "ia", etiqueta: "IA experimental", detalle: modo.split("·")[1]?.trim() };
  if (modo.startsWith("ia")) return { tipo: "ia", etiqueta: "IA", detalle: modo.split("·")[1]?.trim() };
  if (modo.includes("ia_descartada")) return { tipo: "reglas", etiqueta: "Por reglas", detalle: "La redacción con IA se descartó por citar cifras ajenas al motor." };
  return { tipo: "reglas", etiqueta: "Por reglas" };
}

const HERRAMIENTAS: Record<string, string> = {
  "sports.predict": "Análisis de partido",
  "sports.get_odds": "Cuotas del partido",
  "sports.list_fixtures": "Partidos",
  "sports.list_playing_leagues": "Ligas con actividad",
  "sports.list_leagues": "Ligas",
  "sports.list_top_picks": "Top Picks publicados",
  "sports.get_match": "Datos del partido",
  "sports.results": "Verificar resultados",
  "sports.top_picks": "Generar Top Picks",
  "sports.publish": "Publicar en Telegram",
  "agent.ai_prediction": "Hipótesis solo IA",
  "agent.prediction_choice": "Elegir vía de análisis",
  "agent.policy_block": "Política de uso",
  "sports.match_not_found": "Búsqueda de partido",
  "sports.match_required": "Búsqueda de partido",
  "llm.respond": "Respuesta de IA",
  "knowledge.team_profile": "Perfil de equipo",
  "knowledge.league_profile": "Perfil de liga",
  "knowledge.glossary": "Glosario",
};

export function etiquetaHerramienta(nombre: string): string {
  return HERRAMIENTAS[nombre] ?? nombre;
}

/** Respuestas rápidas cuando el agente hace una pregunta cerrada. */
export function respuestasRapidas(herramienta: string | null | undefined): string[] {
  return herramienta === "agent.prediction_choice" ? ["bot", "IA"] : [];
}

export const SUGERENCIAS = [
  "¿Qué partidos hay hoy?",
  "Predice River vs Boca",
  "Explícame qué significa confianza media",
  "¿Qué Top Picks hay publicados hoy?",
];

export const COMANDOS = [
  { comando: "/ayuda", ayuda: "Ver qué puede hacer Laplace" },
  { comando: "/nuevo", ayuda: "Empezar una conversación nueva" },
  { comando: "/tareas", ayuda: "Ver tareas y ejecuciones" },
  { comando: "/subagentes", ayuda: "Consultar subagentes disponibles" },
  { comando: "/memoria", ayuda: "Abrir tu memoria personal" },
  { comando: "/estado", ayuda: "Consultar el estado del bot" },
  { comando: "/top", ayuda: "Ver Top Picks ya publicados" },
  { comando: "/prediccion", ayuda: "Elegir análisis del bot o solo IA" },
];

let contador = 0;
export function nuevoId(): string {
  contador += 1;
  return `m${Date.now().toString(36)}${contador}`;
}
