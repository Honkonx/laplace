import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AdminHistorialPlan } from "./AdminHistorialPlan";

const api = vi.hoisted(() => ({ listarHistorialPlanAdmin: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

describe("AdminHistorialPlan", () => {
  beforeEach(() => { api.listarHistorialPlanAdmin.mockReset(); });

  it("muestra los cambios de plan con guion cuando no había plan anterior", async () => {
    api.listarHistorialPlanAdmin.mockResolvedValue({ total: 2, limit: 50, offset: 0, historial: [
      { id: 1, device_id: "dev-aaa", plan_anterior: null, plan_nuevo: "pro", medio: "codigo", detalle: null, creado_en: "2026-11-02" },
      { id: 2, device_id: "dev-bbb", plan_anterior: "pro", plan_nuevo: "free", medio: "admin", detalle: null, creado_en: "2026-11-03" },
    ] });
    render(<AdminHistorialPlan />);
    const fila1 = (await screen.findByText("dev-aaa")).closest("tr") as HTMLElement;
    expect(fila1).toHaveTextContent("—");
    expect(fila1).toHaveTextContent("codigo");
    expect(screen.getByText("dev-bbb").closest("tr")).toHaveTextContent("admin");
  });

  it("muestra el estado vacío", async () => {
    api.listarHistorialPlanAdmin.mockResolvedValue({ total: 0, limit: 50, offset: 0, historial: [] });
    render(<AdminHistorialPlan />);
    expect(await screen.findByText("Sin cambios de plan registrados.")).toBeInTheDocument();
  });

  it("muestra el error de la API", async () => {
    api.listarHistorialPlanAdmin.mockRejectedValue(new ApiError(500, "Error interno"));
    render(<AdminHistorialPlan />);
    expect(await screen.findByText("Error interno")).toBeInTheDocument();
  });
});
