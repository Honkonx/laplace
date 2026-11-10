import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AuthProvider } from "@/lib/AuthContext";
import { PrediccionCard } from "./PrediccionCard";

const pedirPrediccion = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), pedirPrediccion }));

const partido = { matchId: "99", liga: "Liga X", local: "Colo-Colo", visitante: "U de Chile", fecha: "20261007", hora: "20:00" };

function montar() {
  return render(<MemoryRouter><AuthProvider><PrediccionCard partido={partido} /></AuthProvider></MemoryRouter>);
}

describe("PrediccionCard", () => {
  beforeEach(() => { pedirPrediccion.mockReset(); localStorage.clear(); });

  it("sin sesión no ofrece pedir el pronóstico (el aviso va una sola vez en la lista)", () => {
    montar();
    expect(screen.queryByRole("button", { name: "Ver pronóstico" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Entra" })).not.toBeInTheDocument();
    expect(pedirPrediccion).not.toHaveBeenCalled();
  });

  it("llama al endpoint con los datos del partido y dibuja el resultado", async () => {
    localStorage.setItem("laplace_web_username", "ana");
    pedirPrediccion.mockResolvedValue({
      partido_id: "99", local: "Colo-Colo", visitante: "U de Chile", liga: "Liga X", modulos: {}, modulos_skip: {},
      consenso: { pick_final: "Empate", nivel: "DEBIL", score_consenso: 40, confianza_final: "BAJA", detalle: "", total_modulos: 1, coinciden: 1, prob_ponderada: { local: 0.3, empate: 0.4, visitante: 0.3 }, peso_efectivo: { odds: 1 }, modulos_en_consenso: ["odds"] },
    });
    montar();
    fireEvent.click(screen.getByRole("button", { name: "Ver pronóstico" }));
    await waitFor(() => expect(screen.getByText("Confianza baja")).toBeInTheDocument());
    expect(pedirPrediccion).toHaveBeenCalledWith({ match_id: "99", local: "Colo-Colo", visitante: "U de Chile", liga: "Liga X", fecha: "20261007" });
  });

  it("explica el límite 429 con el tiempo de espera y permite reintentar", async () => {
    localStorage.setItem("laplace_web_username", "ana");
    pedirPrediccion.mockRejectedValue(new ApiError(429, "Demasiadas solicitudes", 30));
    montar();
    fireEvent.click(screen.getByRole("button", { name: "Ver pronóstico" }));
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Demasiadas consultas seguidas");
    expect(alerta).toHaveTextContent("30 s");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
