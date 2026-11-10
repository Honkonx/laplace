import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "@/lib/AuthContext";
import { Home } from "./Home";

const obtenerCatalogoPartidos = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), obtenerCatalogoPartidos }));

const liga = { id: "1", name: "Liga X", logo: null };
const fx = (id: string, pronosticable: boolean) => ({
  id, date: "2026-11-10", kickoff: "20:00", status: "NS", score: { home: null, away: null }, league: liga,
  home: { name: `Local ${id}`, logo: null }, away: { name: `Visita ${id}`, logo: null }, pronosticable,
});

function montar() {
  return render(<MemoryRouter><AuthProvider><Home /></AuthProvider></MemoryRouter>);
}

describe("Home", () => {
  beforeEach(() => { obtenerCatalogoPartidos.mockReset(); localStorage.clear(); });

  it("empieza en «Con pronóstico», cuenta por liga y deja ver todos", async () => {
    obtenerCatalogoPartidos.mockResolvedValue({ fixtures: [fx("1", true), fx("2", false), fx("3", false)], leagues: [], total: 3 });
    montar();
    expect(screen.getByTestId("esqueleto-partidos")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Con pronóstico (1)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("1 de 1 con pronóstico")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Entra" })).toHaveLength(1); // un solo aviso, no uno por tarjeta
    expect(screen.queryByLabelText("Local 2 contra Visita 2")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Todos (3)" }));
    await waitFor(() => expect(screen.getByLabelText("Local 2 contra Visita 2")).toBeInTheDocument());
    expect(screen.getByText("1 de 3 con pronóstico")).toBeInTheDocument();
    expect(localStorage.getItem("laplace_web_modo_pronostico")).toBe("todos");
  });

  it("si ninguno tiene pronóstico arranca en «Todos»", async () => {
    obtenerCatalogoPartidos.mockResolvedValue({ fixtures: [fx("2", false)], leagues: [], total: 1 });
    montar();
    expect(await screen.findByRole("button", { name: "Todos (1)" })).toHaveAttribute("aria-pressed", "true");
  });

  it("con «Con pronóstico» guardado y sin ninguno, muestra el estado vacío con salida", async () => {
    localStorage.setItem("laplace_web_modo_pronostico", "con");
    obtenerCatalogoPartidos.mockResolvedValue({ fixtures: [fx("2", false)], leagues: [], total: 1 });
    montar();
    fireEvent.click(await screen.findByRole("button", { name: "Ver todos los partidos" }));
    expect(await screen.findByLabelText("Local 2 contra Visita 2")).toBeInTheDocument();
  });
});
