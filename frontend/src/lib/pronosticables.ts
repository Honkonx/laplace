import type { WebFixture } from "@/lib/api";

export type ModoPronostico = "con" | "todos";

const CLAVE_MODO = "laplace_web_modo_pronostico";

export interface Conteo { con: number; total: number; }

export function contarPronosticables(fixtures: ReadonlyArray<Pick<WebFixture, "pronosticable">>): Conteo {
  return { con: fixtures.filter((f) => f.pronosticable === true).length, total: fixtures.length };
}

/** Sin elección guardada del usuario: «con» solo si hay algo que mostrar. */
export function modoPorDefecto(conteo: Conteo, elegido: ModoPronostico | null): ModoPronostico {
  return elegido ?? (conteo.con > 0 ? "con" : "todos");
}

export function filtrarPorModo<T extends Pick<WebFixture, "pronosticable">>(fixtures: readonly T[], modo: ModoPronostico): T[] {
  return modo === "con" ? fixtures.filter((f) => f.pronosticable === true) : [...fixtures];
}

/** Los pronosticables primero; el orden relativo del resto se conserva. */
export function pronosticablesPrimero<T extends Pick<WebFixture, "pronosticable">>(fixtures: readonly T[]): T[] {
  return [...fixtures].sort((a, b) => Number(b.pronosticable === true) - Number(a.pronosticable === true));
}

// El storage puede no existir (modo privado, política del navegador): la pantalla funciona igual.
export function leerModoGuardado(): ModoPronostico | null {
  try {
    const valor = window.localStorage.getItem(CLAVE_MODO);
    return valor === "con" || valor === "todos" ? valor : null;
  } catch {
    return null;
  }
}

export function guardarModo(modo: ModoPronostico): void {
  try {
    window.localStorage.setItem(CLAVE_MODO, modo);
  } catch {
    /* sin storage: la elección solo dura la sesión */
  }
}
