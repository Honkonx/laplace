import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Simulador } from "@/pages/Simulador";

const sesion = { username: null as string | null, plan: null as string | null, rol: null as string | null };
vi.mock("@/lib/AuthContext", () => ({ useAuth: () => sesion }));

const LIGAS = { ligas: [{ slug: "premier", nombre: "Premier League", disponible: true }, { slug: "laliga", nombre: "La Liga", disponible: true }], requiere: "plan pro o max", mensaje: "x" };
const SIMULACION = { ok: true, liga_nombre: "Premier League", n_simulaciones: 10000, partidos_jugados: 100, partidos_pendientes: 280, datos_hasta: "2026-11-08", aviso: "Estimación estadística.", tabla: { Arsenal: { prob_campeon: 0.6, prob_copa: 0.99, prob_descenso: 0, posicion_promedio: 1.6, puntos: { p05: 73, p50: 85, p95: 98, media: 85 } } } };

function respuesta(cuerpo: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(cuerpo), { status, headers: { "Content-Type": "application/json" } }));
}

describe("Simulador", () => {
  beforeEach(() => {
    sesion.username = null; sesion.plan = null; sesion.rol = null;
    vi.stubGlobal("fetch", vi.fn((url: string) => (String(url).endsWith("/api/v1/simulador") ? respuesta(LIGAS) : respuesta(SIMULACION))));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sin sesión avisa que es de los planes pro y max y no deja simular", () => {
    render(<MemoryRouter><Simulador /></MemoryRouter>);
    expect(screen.getByText(/planes pro y max/i)).toBeTruthy();
    expect((screen.getByRole("button", { name: /Simular temporada/i }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("link", { name: /Entrar/i })).toBeTruthy();
  });

  it("un plan free ve su plan y el botón sigue bloqueado", () => {
    sesion.username = "ana"; sesion.plan = "free";
    render(<MemoryRouter><Simulador /></MemoryRouter>);
    expect(screen.getByText(/Tu plan es FREE/i)).toBeTruthy();
    expect((screen.getByRole("button", { name: /Simular temporada/i }) as HTMLButtonElement).disabled).toBe(true);
  });

  it.each([["pro", "usuario"], ["max", "usuario"], ["free", "admin"]])("plan %s con rol %s puede simular y ve los datos de procedencia", async (plan, rol) => {
    sesion.username = "ana"; sesion.plan = plan; sesion.rol = rol;
    render(<MemoryRouter><Simulador /></MemoryRouter>);
    const boton = screen.getByRole("button", { name: /Simular temporada/i }) as HTMLButtonElement;
    expect(boton.disabled).toBe(false);
    await userEvent.click(boton);
    await waitFor(() => expect(screen.getByText("Arsenal")).toBeTruthy());
    expect(screen.getByText(/datos hasta 2026-11-08/)).toBeTruthy();
    expect(screen.getByText("73–98")).toBeTruthy();
    expect(screen.getByText("60%")).toBeTruthy();
  });

  it("si el servidor responde 403 se muestra su mensaje", async () => {
    sesion.username = "ana"; sesion.plan = "pro";
    vi.stubGlobal("fetch", vi.fn((url: string) => (String(url).endsWith("/api/v1/simulador") ? respuesta(LIGAS) : respuesta({ detail: "El simulador de liga es de los planes pro y max." }, 403))));
    render(<MemoryRouter><Simulador /></MemoryRouter>);
    await userEvent.click(screen.getByRole("button", { name: /Simular temporada/i }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/planes pro y max/));
  });
});
