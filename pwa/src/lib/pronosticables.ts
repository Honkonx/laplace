import type { WebFixture } from "@/lib/api";

export type Vista = "con" | "todos";

export interface Conteo { con: number; todos: number }
export interface GrupoLiga { id: string; nombre: string; partidos: WebFixture[]; con: number }

const CLAVE_VISTA = "laplace.vistaPartidos";

export function contar(partidos: WebFixture[]): Conteo {
  return { con: partidos.filter((p) => p.pronosticable).length, todos: partidos.length };
}

export function vistaPorDefecto(conteo: Conteo, guardada: Vista | null): Vista {
  if (conteo.con === 0) return "todos";
  return guardada ?? "con";
}

export function filtrarPorVista(partidos: WebFixture[], vista: Vista): WebFixture[] {
  return vista === "con" ? partidos.filter((p) => p.pronosticable) : partidos;
}

export function agruparPorLiga(partidos: WebFixture[]): GrupoLiga[] {
  const grupos = new Map<string, GrupoLiga>();
  for (const partido of partidos) {
    const clave = `${partido.league.id}-${partido.league.name}`;
    const grupo = grupos.get(clave) ?? { id: clave, nombre: partido.league.name, partidos: [], con: 0 };
    grupo.partidos.push(partido);
    if (partido.pronosticable) grupo.con += 1;
    grupos.set(clave, grupo);
  }
  return [...grupos.values()].sort((a, b) => b.con - a.con);
}

export function leerVistaGuardada(): Vista | null {
  try {
    const valor = window.localStorage.getItem(CLAVE_VISTA);
    return valor === "con" || valor === "todos" ? valor : null;
  } catch {
    return null;
  }
}

export function guardarVista(vista: Vista): void {
  try {
    window.localStorage.setItem(CLAVE_VISTA, vista);
  } catch {
    // Sin storage (modo privado): la elección vale solo para esta sesión.
  }
}
