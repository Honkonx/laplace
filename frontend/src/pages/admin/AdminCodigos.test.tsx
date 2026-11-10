import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AdminCodigos } from "./AdminCodigos";

const api = vi.hoisted(() => ({ listarCodigosAdmin: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

describe("AdminCodigos", () => {
  beforeEach(() => { api.listarCodigosAdmin.mockReset(); });

  it("lista los códigos con su estado de uso", async () => {
    api.listarCodigosAdmin.mockResolvedValue({ filtro: "todos", total: 2, codigos: [
      { codigo: "ABC-123", plan: "pro", dias: 30, usado: false, device_id_asignado: null, device_id_usado: null, creado_en: "2026-11-01", usado_en: null },
      { codigo: "XYZ-999", plan: "max", dias: 90, usado: true, device_id_asignado: "dev-1", device_id_usado: "dev-2", creado_en: "2026-11-01", usado_en: "2026-11-02" },
    ] });
    render(<AdminCodigos />);
    expect(await screen.findByText("ABC-123")).toBeInTheDocument();
    expect(screen.getByText("XYZ-999").closest("tr")).toHaveTextContent("dev-2");
    expect(screen.getByText("ABC-123").closest("tr")).toHaveTextContent("No");
  });

  it("muestra el estado vacío", async () => {
    api.listarCodigosAdmin.mockResolvedValue({ filtro: "todos", total: 0, codigos: [] });
    render(<AdminCodigos />);
    expect(await screen.findByText("Sin códigos.")).toBeInTheDocument();
  });

  it("muestra el mensaje del backend si la API falla", async () => {
    api.listarCodigosAdmin.mockRejectedValue(new ApiError(403, "Solo administradores"));
    render(<AdminCodigos />);
    expect(await screen.findByText("Solo administradores")).toBeInTheDocument();
  });

  it("usa un mensaje genérico ante un error que no es de la API", async () => {
    api.listarCodigosAdmin.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<AdminCodigos />);
    expect(await screen.findByText("No se pudo cargar la información.")).toBeInTheDocument();
  });
});
