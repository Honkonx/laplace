import { afterEach, describe, expect, it, vi } from "vitest";
import { contarPronosticables, filtrarPorModo, guardarModo, leerModoGuardado, modoPorDefecto, pronosticablesPrimero } from "./pronosticables";

const f = (id: string, pronosticable?: boolean) => ({ id, pronosticable });

describe("pronosticables", () => {
  afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

  it("cuenta solo los marcados como pronosticables", () => {
    expect(contarPronosticables([f("1", true), f("2", false), f("3")])).toEqual({ con: 1, total: 3 });
    expect(contarPronosticables([])).toEqual({ con: 0, total: 0 });
  });

  it("por defecto elige «con» solo si hay alguno, y respeta lo elegido", () => {
    expect(modoPorDefecto({ con: 2, total: 5 }, null)).toBe("con");
    expect(modoPorDefecto({ con: 0, total: 5 }, null)).toBe("todos");
    expect(modoPorDefecto({ con: 2, total: 5 }, "todos")).toBe("todos");
  });

  it("filtra y ordena sin mutar la entrada", () => {
    const lista = [f("1", false), f("2", true), f("3", true)];
    expect(filtrarPorModo(lista, "con").map((x) => x.id)).toEqual(["2", "3"]);
    expect(filtrarPorModo(lista, "todos")).toHaveLength(3);
    expect(pronosticablesPrimero(lista).map((x) => x.id)).toEqual(["2", "3", "1"]);
    expect(lista.map((x) => x.id)).toEqual(["1", "2", "3"]);
  });

  it("guarda y lee la elección; ignora valores raros", () => {
    expect(leerModoGuardado()).toBeNull();
    guardarModo("todos");
    expect(leerModoGuardado()).toBe("todos");
    localStorage.setItem("laplace_web_modo_pronostico", "otro");
    expect(leerModoGuardado()).toBeNull();
  });

  it("funciona sin storage disponible", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("bloqueado"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("bloqueado"); });
    expect(leerModoGuardado()).toBeNull();
    expect(() => guardarModo("con")).not.toThrow();
  });
});
