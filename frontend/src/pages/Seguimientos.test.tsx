import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Seguimientos } from "@/pages/Seguimientos";

const sesion = { username: "ana" as string | null, plan: "pro", rol: "usuario" };
vi.mock("@/lib/AuthContext", () => ({ useAuth: () => sesion }));

const RESUMEN = {
  equipos: ["Colo-Colo"], ligas: ["Premier League"], consentimiento: true, avisos: false, plan: "pro",
  limites: { equipos: 5, ligas: 3, partidos_24h: 4 },
  perfil: { zona_horaria: null, estilo: null, mercados: [] },
};

type Llamada = { metodo: string; url: string; cuerpo: unknown };
let llamadas: Llamada[];
let rutas: Record<string, () => Response>;

const json = (c: unknown, status = 200) => new Response(JSON.stringify(c), { status, headers: { "Content-Type": "application/json" } });

function montar() {
  render(<MemoryRouter><Seguimientos /></MemoryRouter>);
}

beforeEach(() => {
  sesion.username = "ana";
  llamadas = [];
  rutas = { "GET /api/v1/agent/seguimientos": () => json(RESUMEN) };
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    const metodo = init?.method ?? "GET";
    const ruta = new URL(String(url)).pathname;
    llamadas.push({ metodo, url: String(url), cuerpo: init?.body ? JSON.parse(String(init.body)) : undefined });
    const resp = rutas[`${metodo} ${ruta}`];
    return Promise.resolve(resp ? resp() : json({ detail: "sin ruta" }, 404));
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("Seguimientos", () => {
  it("sin sesión pide entrar y no llama a la API", () => {
    sesion.username = null;
    montar();
    expect(screen.getByRole("link", { name: /Entrar/i })).toBeTruthy();
    expect(llamadas).toHaveLength(0);
  });

  it("carga y muestra equipos, ligas y contadores", async () => {
    montar();
    expect(screen.getByText(/Cargando/)).toBeTruthy();
    expect(await screen.findByText("Colo-Colo")).toBeTruthy();
    expect(screen.getByText("Premier League")).toBeTruthy();
    expect(screen.getByText("1 de 5")).toBeTruthy();
    expect(screen.getByText("1 de 3")).toBeTruthy();
    expect(screen.queryByText(/Todavía no sigues nada/)).toBeNull();
  });

  it("vacío muestra el texto de que no sigue nada", async () => {
    rutas["GET /api/v1/agent/seguimientos"] = () => json({ ...RESUMEN, equipos: [], ligas: [] });
    montar();
    expect(await screen.findByText(/Todavía no sigues nada/)).toBeTruthy();
  });

  it("error de red y sesión expirada se muestran en una alerta", async () => {
    rutas["GET /api/v1/agent/seguimientos"] = () => json({ detail: "x" }, 401);
    montar();
    expect((await screen.findByRole("alert")).textContent).toMatch(/Vuelve a entrar/);
  });

  it("añadir un equipo: manda el cuerpo, muestra el mensaje y actualiza la lista", async () => {
    rutas["POST /api/v1/agent/seguimientos"] = () =>
      json({ ...RESUMEN, equipos: ["Colo-Colo", "Universidad de Chile"], ok: true, mensaje: "Listo, sigues a Universidad de Chile." });
    montar();
    await screen.findByText("Colo-Colo");
    await userEvent.type(screen.getByLabelText("Nombre del equipo"), "Universidad de Chile");
    await userEvent.click(within_form("Seguir equipo"));
    expect(await screen.findByText(/sigues a Universidad de Chile/)).toBeTruthy();
    expect(llamadas.find((l) => l.metodo === "POST")?.cuerpo).toEqual({ tipo: "equipo", nombre: "Universidad de Chile" });
    expect(await screen.findByText("2 de 5")).toBeTruthy();
  });

  it("añadir con error de la API muestra su mensaje", async () => {
    rutas["POST /api/v1/agent/seguimientos"] = () => json({ ok: false, mensaje: "No encontré ese equipo." });
    montar();
    await screen.findByText("Colo-Colo");
    await userEvent.type(screen.getByLabelText("Nombre de la liga"), "Liga Inventada");
    await userEvent.click(within_form("Seguir liga"));
    expect((await screen.findByRole("status")).textContent).toBe("No encontré ese equipo.");
    expect(llamadas.find((l) => l.metodo === "POST")?.cuerpo).toEqual({ tipo: "liga", nombre: "Liga Inventada" });
  });

  it("dejar de seguir llama a DELETE con el nombre codificado", async () => {
    rutas["DELETE /api/v1/agent/seguimientos"] = () => json({ ...RESUMEN, equipos: [], ok: true, mensaje: "Dejaste de seguir a Colo-Colo." });
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "Dejar de seguir Colo-Colo" }));
    expect(await screen.findByText(/Dejaste de seguir/)).toBeTruthy();
    expect(llamadas.find((l) => l.metodo === "DELETE")?.url).toContain("?nombre=Colo-Colo");
    await waitFor(() => expect(screen.queryByText("Colo-Colo")).toBeNull());
  });

  it("el interruptor de avisos manda activar y refleja el resumen", async () => {
    rutas["PUT /api/v1/agent/seguimientos/avisos"] = () => json({ ...RESUMEN, avisos: true, ok: true, mensaje: "Avisos activados." });
    montar();
    await userEvent.click(await screen.findByRole("switch"));
    expect(await screen.findByText("Avisos activados.")).toBeTruthy();
    expect(llamadas.find((l) => l.metodo === "PUT")?.cuerpo).toEqual({ activar: true });
    await waitFor(() => expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(true));
  });

  it("guarda el perfil con zona, estilo y mercados", async () => {
    rutas["PUT /api/v1/agent/perfil"] = () => json({ ...RESUMEN, ok: true, mensaje: "Perfil guardado." });
    montar();
    await screen.findByText("Colo-Colo");
    await userEvent.type(screen.getByLabelText("Zona horaria"), "Chile");
    await userEvent.click(screen.getByLabelText("Técnico"));
    await userEvent.click(screen.getByLabelText("goles"));
    await userEvent.click(screen.getByRole("button", { name: "Guardar perfil" }));
    expect(await screen.findByText("Perfil guardado.")).toBeTruthy();
    expect(llamadas.find((l) => l.url.endsWith("/perfil"))?.cuerpo).toEqual({ zona_horaria: "Chile", estilo: "tecnico", mercados: ["goles"] });
  });

  it("borra el perfil", async () => {
    rutas["DELETE /api/v1/agent/perfil"] = () => json({ ...RESUMEN, ok: true, mensaje: "Perfil borrado." });
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "Borrar perfil" }));
    expect(await screen.findByText("Perfil borrado.")).toBeTruthy();
  });

  it("sin consentimiento deshabilita los controles y Aceptar lo da", async () => {
    rutas["GET /api/v1/agent/seguimientos"] = () => json({ ...RESUMEN, consentimiento: false });
    rutas["POST /api/v1/agent/seguimientos/consentimiento"] = () => json({ ...RESUMEN, ok: true, mensaje: "Gracias, listo." });
    montar();
    const aceptar = await screen.findByRole("button", { name: "Aceptar" });
    for (const nombre of ["Dejar de seguir Colo-Colo", "Guardar perfil", "Borrar perfil"]) {
      const b = screen.getByRole("button", { name: nombre }) as HTMLButtonElement;
      expect(b.disabled, nombre).toBe(true);
      expect(b.title).toMatch(/Acepta primero/);
    }
    expect((screen.getByRole("switch") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("Nombre del equipo") as HTMLInputElement).disabled).toBe(true);
    await userEvent.click(aceptar);
    expect(await screen.findByText("Gracias, listo.")).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Aceptar" })).toBeNull());
    expect((screen.getByRole("switch") as HTMLInputElement).disabled).toBe(false);
  });

  it("en el límite del plan el formulario queda bloqueado", async () => {
    rutas["GET /api/v1/agent/seguimientos"] = () => json({ ...RESUMEN, limites: { ...RESUMEN.limites, equipos: 1 } });
    montar();
    await screen.findByText("1 de 1");
    expect((screen.getByLabelText("Nombre del equipo") as HTMLInputElement).disabled).toBe(true);
  });
});

function within_form(nombre: string): HTMLElement {
  const form = screen.getByRole("form", { name: nombre });
  const boton = form.querySelector("button");
  if (!boton) throw new Error("sin botón");
  return boton;
}
