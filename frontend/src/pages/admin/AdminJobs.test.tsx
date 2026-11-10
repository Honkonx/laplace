import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AdminJobs } from "./AdminJobs";

const api = vi.hoisted(() => ({ listarJobsAdmin: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const JOB = { job_id: "job-1", match_id: "m-77", fecha_partido: "2026-11-09", origen: "web", status: "listo", intentos: 1, plan: "pro", device_id_app: null, creado_en: "2026-11-09 09:00", completado_en: null };

describe("AdminJobs", () => {
  beforeEach(() => { api.listarJobsAdmin.mockReset(); });

  it("muestra los jobs con guion si no se completaron", async () => {
    api.listarJobsAdmin.mockResolvedValue({ total: 1, limit: 50, offset: 0, jobs: [JOB] });
    render(<AdminJobs />);
    const fila = (await screen.findByText("job-1")).closest("tr") as HTMLElement;
    expect(fila).toHaveTextContent("m-77 · 2026-11-09");
    expect(fila).toHaveTextContent("—");
  });

  it("filtra por status volviendo a pedir a la API", async () => {
    api.listarJobsAdmin.mockResolvedValue({ total: 1, limit: 50, offset: 0, jobs: [JOB] });
    render(<AdminJobs />);
    await screen.findByText("job-1");
    expect(api.listarJobsAdmin).toHaveBeenLastCalledWith({});
    fireEvent.change(screen.getByPlaceholderText(/Filtrar por status/), { target: { value: "error" } });
    await waitFor(() => expect(api.listarJobsAdmin).toHaveBeenLastCalledWith({ status: "error" }));
  });

  it("muestra el estado vacío", async () => {
    api.listarJobsAdmin.mockResolvedValue({ total: 0, limit: 50, offset: 0, jobs: [] });
    render(<AdminJobs />);
    expect(await screen.findByText("Sin jobs.")).toBeInTheDocument();
  });

  it("muestra el error de la API", async () => {
    api.listarJobsAdmin.mockRejectedValue(new ApiError(500, "Cola caída"));
    render(<AdminJobs />);
    expect(await screen.findByText("Cola caída")).toBeInTheDocument();
  });
});
