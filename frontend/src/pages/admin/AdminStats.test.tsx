import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AdminStats } from "./AdminStats";

const api = vi.hoisted(() => ({ obtenerStatsAdmin: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const STATS = {
  periodo_dias: 30, desde: "2026-10-10",
  por_fuente: [{ fuente: "consenso", total: 40, evaluados: 20, aciertos: 11, winrate: 55 }],
  pick_final: { total: 40, evaluados: 20, aciertos: 11, winrate: 55, alta_winrate: 70.5, media_winrate: null, consenso_winrate: 55 },
};

describe("AdminStats", () => {
  beforeEach(() => { api.obtenerStatsAdmin.mockReset(); });

  it("muestra el winrate y un guion cuando no hay evaluados", async () => {
    api.obtenerStatsAdmin.mockResolvedValue(STATS);
    render(<AdminStats />);
    expect(await screen.findByText(/Últimos 30 días/)).toBeInTheDocument();
    expect(screen.getByText("Winrate confianza ALTA").nextElementSibling).toHaveTextContent("70.5%");
    expect(screen.getByText("Winrate confianza MEDIA").nextElementSibling).toHaveTextContent("—");
    expect(screen.getByText("consenso").closest("tr")).toHaveTextContent("55%");
    expect(api.obtenerStatsAdmin).toHaveBeenCalledWith(30);
  });

  it("muestra el estado vacío por fuente", async () => {
    api.obtenerStatsAdmin.mockResolvedValue({ ...STATS, por_fuente: [] });
    render(<AdminStats />);
    expect(await screen.findByText("Sin datos en el período.")).toBeInTheDocument();
  });

  it("muestra el error de la API", async () => {
    api.obtenerStatsAdmin.mockRejectedValue(new ApiError(403, "Solo administradores"));
    render(<AdminStats />);
    expect(await screen.findByText("Solo administradores")).toBeInTheDocument();
  });
});
