import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { App } from "@/App";

vi.mock("@/lib/AuthContext", async (original) => {
  const real = await original<typeof import("@/lib/AuthContext")>();
  return { ...real, AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>, useAuth: () => ({ username: null, plan: null, rol: null, cargando: false, iniciarSesion: vi.fn(), registrarse: vi.fn(), activarCodigo: vi.fn(), cerrarSesion: vi.fn() }) };
});

describe("rutas de la PWA", () => {
  it("existen las mismas pantallas que en la web (historial, estado, simulador, entrar) y una dirección rota no deja la página en blanco", () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("{}", { status: 200 }))));
    for (const ruta of ["/historial", "/estado", "/simulador", "/entrar", "/no-existe"]) {
      window.history.pushState({}, "", ruta);
      const { container, unmount } = render(<App />);
      expect(container.textContent?.trim().length ?? 0, ruta).toBeGreaterThan(20);
      unmount();
    }
    window.history.pushState({}, "", "/no-existe");
    render(<App />);
    expect(screen.getAllByText(/No encontramos esa página/i).length).toBeGreaterThan(0);
    vi.unstubAllGlobals();
  });
});
