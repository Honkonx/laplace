import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AdminConexiones } from "./AdminConexiones";

const api = vi.hoisted(() => ({
  obtenerConexionesAdmin: vi.fn(), probarConexionAdmin: vi.fn(), guardarConexionAdmin: vi.fn(), borrarConexionAdmin: vi.fn(), guardarOrdenIaAdmin: vi.fn(),
}));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const base = { variable: "X", sirve: "algo", plan: "gratis", enlace: "https://ejemplo.test/clave", host: "api.ejemplo.test", destacada: false, cobra_por_llamada: false, cuesta: null };
const DATOS = {
  grupos: [{ id: "cuotas", titulo: "CUOTAS DEL MERCADO", nota: "" }, { id: "ia", titulo: "IA", nota: "" }],
  conexiones: [
    { ...base, id: "the-odds-api", numero: 4, grupo: "cuotas", nombre: "The Odds API", variable: "THE_ODDS_API_KEY", configurada: true, destacada: true },
    { ...base, id: "ollama_cloud", numero: 7, grupo: "ia", nombre: "Ollama Cloud", variable: "OLLAMA_API_KEY", configurada: true, cuesta: "≈ 1 token" },
    { ...base, id: "groq", numero: 8, grupo: "ia", nombre: "Groq", variable: "GROQ_API_KEY", configurada: false },
  ],
  faltantes: ["sin ningún calendario (LiveScore6, BSD o api-football): no se verán partidos"],
  orden_ia: ["ollama_cloud", "groq", "gemini", "openrouter", "claude"],
  nota: "Las claves se guardan en .env.",
};

describe("AdminConexiones", () => {
  beforeEach(() => { Object.values(api).forEach((f) => f.mockReset()); api.obtenerConexionesAdmin.mockResolvedValue(DATOS); });

  it("muestra cada conexión con su estado y avisa de lo que falta para pronosticar", async () => {
    render(<AdminConexiones />);
    expect(await screen.findByRole("article", { name: "The Odds API" })).toHaveTextContent("configurada (sin probar)");
    expect(screen.getByRole("article", { name: "Groq" })).toHaveTextContent("sin clave");
    expect(screen.getByRole("status")).toHaveTextContent("sin ningún calendario");
    expect(screen.getAllByRole("link", { name: /Conseguir clave/ })[0]).toHaveAttribute("href", "https://ejemplo.test/clave");
  });

  it("prueba una conexión y muestra el resultado", async () => {
    api.probarConexionAdmin.mockResolvedValue({ id: "the-odds-api", estado: "ok", detalle: "válida · 500 créditos", requiere_confirmacion: false });
    render(<AdminConexiones />);
    const tarjeta = await screen.findByRole("article", { name: "The Odds API" });
    fireEvent.click(tarjeta.querySelector("button.btn:not(.btn-primary)") as HTMLElement);
    await waitFor(() => expect(tarjeta).toHaveTextContent("✓ válida · 500 créditos"));
    expect(api.probarConexionAdmin).toHaveBeenCalledWith("the-odds-api", false);
  });

  it("guarda una clave sin volver a mostrarla y recarga la lista", async () => {
    api.guardarConexionAdmin.mockResolvedValue({ id: "groq", estado: "ok", detalle: "válida", message: "Guardada en .env." });
    render(<AdminConexiones />);
    const tarjeta = await screen.findByRole("article", { name: "Groq" });
    fireEvent.click(screen.getAllByRole("button", { name: "Poner clave" })[0]);
    const campo = screen.getByLabelText("Clave de Groq") as HTMLInputElement;
    expect(campo.type).toBe("password");
    fireEvent.change(campo, { target: { value: "gsk_clave-super-secreta-123" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(api.guardarConexionAdmin).toHaveBeenCalledWith("groq", "gsk_clave-super-secreta-123", false));
    expect(await screen.findByText(/Groq: Guardada en \.env\./)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("gsk_clave-super-secreta-123");
    expect(api.obtenerConexionesAdmin).toHaveBeenCalledTimes(2);
    expect(tarjeta).toBeInTheDocument();
  });

  it("si el proveedor rechaza la clave, lo dice y no da por guardada ninguna", async () => {
    api.guardarConexionAdmin.mockRejectedValue(new ApiError(422, "clave inválida (HTTP 401). No se guardó nada; la clave anterior sigue como estaba."));
    render(<AdminConexiones />);
    await screen.findByRole("article", { name: "Groq" });
    fireEvent.click(screen.getAllByRole("button", { name: "Poner clave" })[0]);
    fireEvent.change(screen.getByLabelText("Clave de Groq"), { target: { value: "clave-mala-123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No se guardó nada");
    expect(api.obtenerConexionesAdmin).toHaveBeenCalledTimes(1);
  });

  it("las pruebas con coste piden confirmación antes de hacerse", async () => {
    api.probarConexionAdmin.mockResolvedValueOnce({ id: "ollama_cloud", estado: "warn", detalle: "cuesta", requiere_confirmacion: true, coste: "≈ 1 token" });
    api.probarConexionAdmin.mockResolvedValueOnce({ id: "ollama_cloud", estado: "ok", detalle: "válida", requiere_confirmacion: false });
    render(<AdminConexiones />);
    const tarjeta = await screen.findByRole("article", { name: "Ollama Cloud" });
    fireEvent.click(tarjeta.querySelector("button.btn:not(.btn-primary)") as HTMLElement);
    expect(await screen.findByText(/Esta prueba cuesta ≈ 1 token/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Probar igual" }));
    await waitFor(() => expect(api.probarConexionAdmin).toHaveBeenLastCalledWith("ollama_cloud", true));
    await waitFor(() => expect(tarjeta).toHaveTextContent("✓ válida"));
  });

  it("borrar pide confirmación y no borra con un solo clic", async () => {
    api.borrarConexionAdmin.mockResolvedValue({ id: "the-odds-api", message: "Clave borrada de .env." });
    render(<AdminConexiones />);
    const tarjeta = await screen.findByRole("article", { name: "The Odds API" });
    fireEvent.click(Array.from(tarjeta.querySelectorAll("button")).find((b) => b.textContent === "Borrar") as HTMLElement);
    expect(api.borrarConexionAdmin).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Sí, borrar" }));
    await waitFor(() => expect(api.borrarConexionAdmin).toHaveBeenCalledWith("the-odds-api"));
  });

  it("reordena la IA y guarda el orden", async () => {
    api.guardarOrdenIaAdmin.mockResolvedValue({ orden: [], message: "Orden guardado." });
    render(<AdminConexiones />);
    await screen.findByText("Orden de la IA");
    fireEvent.click(screen.getByRole("button", { name: "Bajar Ollama Cloud" }));
    fireEvent.click(screen.getByRole("button", { name: "Guardar orden" }));
    await waitFor(() => expect(api.guardarOrdenIaAdmin).toHaveBeenCalledWith(["groq", "ollama_cloud", "gemini", "openrouter", "claude"]));
  });
});
