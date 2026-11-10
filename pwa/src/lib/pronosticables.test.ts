import { afterEach, describe, expect, it, vi } from "vitest";
import type { WebFixture } from "@/lib/api";
import { agruparPorLiga, contar, filtrarPorVista, guardarVista, leerVistaGuardada, vistaPorDefecto } from "./pronosticables";

const partido = (id: string, liga: string, pronosticable?: boolean): WebFixture => ({
  id, date: "2026-11-09", kickoff: null, status: "NS", pronosticable,
  league: { id: liga, name: `Liga ${liga}`, logo: null }, home: { name: "A", logo: null }, away: { name: "B", logo: null },
});
const lista = [partido("1", "x", true), partido("2", "x"), partido("3", "y", false), partido("4", "y", true), partido("5", "y", true)];

afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear(); });

describe("pronosticables", () => {
  it("cuenta con pronóstico y total", () => {
    expect(contar(lista)).toEqual({ con: 3, todos: 5 });
    expect(contar([])).toEqual({ con: 0, todos: 0 });
  });
  it("elige la vista por defecto", () => {
    expect(vistaPorDefecto({ con: 2, todos: 5 }, null)).toBe("con");
    expect(vistaPorDefecto({ con: 0, todos: 5 }, "con")).toBe("todos");
    expect(vistaPorDefecto({ con: 2, todos: 5 }, "todos")).toBe("todos");
  });
  it("filtra por vista", () => {
    expect(filtrarPorVista(lista, "con").map((p) => p.id)).toEqual(["1", "4", "5"]);
    expect(filtrarPorVista(lista, "todos")).toHaveLength(5);
  });
  it("agrupa por liga con su conteo, las de más pronósticos primero", () => {
    const grupos = agruparPorLiga(lista);
    expect(grupos.map((g) => [g.nombre, g.con, g.partidos.length])).toEqual([["Liga y", 2, 3], ["Liga x", 1, 2]]);
  });
  it("guarda y lee la vista; sin storage no falla", () => {
    guardarVista("todos");
    expect(leerVistaGuardada()).toBe("todos");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denegado"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("denegado"); });
    expect(leerVistaGuardada()).toBeNull();
    expect(() => guardarVista("con")).not.toThrow();
  });
});
