import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AdminUsuarios } from "./AdminUsuarios";

const api = vi.hoisted(() => ({ listarUsuariosAdmin: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const usuario = (id: number, username: string, activo = true) => ({ id, device_id: `d${id}`, username, activo, plan: "free", origen: "web", nickname: null, activo_hasta: null, creado_en: "2026-11-01" });

describe("AdminUsuarios", () => {
  beforeEach(() => { api.listarUsuariosAdmin.mockReset(); });

  it("lista usuarios con su estado y el total", async () => {
    api.listarUsuariosAdmin.mockResolvedValue({ total: 2, limit: 20, offset: 0, usuarios: [usuario(1, "ana"), usuario(2, "beto", false)] });
    render(<AdminUsuarios />);
    expect((await screen.findByText("ana")).closest("tr")).toHaveTextContent("Sí");
    expect(screen.getByText("beto").closest("tr")).toHaveTextContent("No");
    expect(screen.getByText("2 usuarios en total")).toBeInTheDocument();
  });

  it("pagina y busca por usuario", async () => {
    api.listarUsuariosAdmin.mockResolvedValue({ total: 45, limit: 20, offset: 0, usuarios: [usuario(1, "ana")] });
    render(<AdminUsuarios />);
    await screen.findByText("ana");
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    await waitFor(() => expect(api.listarUsuariosAdmin).toHaveBeenLastCalledWith({ limit: 20, offset: 20, q: undefined }));
    fireEvent.change(screen.getByPlaceholderText("Buscar por usuario…"), { target: { value: "an" } });
    await waitFor(() => expect(api.listarUsuariosAdmin).toHaveBeenLastCalledWith({ limit: 20, offset: 0, q: "an" }));
  });

  it("muestra el estado vacío", async () => {
    api.listarUsuariosAdmin.mockResolvedValue({ total: 0, limit: 20, offset: 0, usuarios: [] });
    render(<AdminUsuarios />);
    expect(await screen.findByText("Sin resultados.")).toBeInTheDocument();
  });

  it("muestra el error de la API", async () => {
    api.listarUsuariosAdmin.mockRejectedValue(new ApiError(500, "Base no disponible"));
    render(<AdminUsuarios />);
    expect(await screen.findByText("Base no disponible")).toBeInTheDocument();
  });
});
