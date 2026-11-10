import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AdminIntentosLogin } from "./AdminIntentosLogin";

const api = vi.hoisted(() => ({ listarIntentosLoginAdmin: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

describe("AdminIntentosLogin", () => {
  beforeEach(() => { api.listarIntentosLoginAdmin.mockReset(); });

  it("lista los usuarios intentados", async () => {
    api.listarIntentosLoginAdmin.mockResolvedValue({ total: 2, limit: 50, offset: 0, intentos: [
      { id: 1, username_intentado: "admin", creado_en: "2026-11-05 10:00" },
      { id: 2, username_intentado: "root", creado_en: "2026-11-05 10:01" },
    ] });
    render(<AdminIntentosLogin />);
    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(screen.getByText("root").closest("tr")).toHaveTextContent("2026-11-05 10:01");
  });

  it("muestra el estado vacío", async () => {
    api.listarIntentosLoginAdmin.mockResolvedValue({ total: 0, limit: 50, offset: 0, intentos: [] });
    render(<AdminIntentosLogin />);
    expect(await screen.findByText("Sin intentos fallidos registrados.")).toBeInTheDocument();
  });

  it("muestra el error de la API", async () => {
    api.listarIntentosLoginAdmin.mockRejectedValue(new ApiError(401, "Sesión vencida"));
    render(<AdminIntentosLogin />);
    expect(await screen.findByText("Sesión vencida")).toBeInTheDocument();
  });
});
