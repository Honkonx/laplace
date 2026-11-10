import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownLite } from "@/components/chat/MarkdownLite";
import { fuenteDeModo } from "./chat";
import { describirError } from "./errores";
import { ApiError } from "./api";

describe("fuenteDeModo", () => {
  it("distingue reglas de IA y explica los fallbacks", () => {
    expect(fuenteDeModo("reglas")?.tipo).toBe("reglas");
    expect(fuenteDeModo("ia · gemini/flash")).toMatchObject({ tipo: "ia", detalle: "gemini/flash" });
    expect(fuenteDeModo("reglas_fallback")?.detalle).toMatch(/IA no estaba disponible/);
    expect(fuenteDeModo("reglas · ia_descartada x/y")?.detalle).toMatch(/descartó/);
    expect(fuenteDeModo("entrada")).toBeNull();
  });
});

describe("describirError", () => {
  it("429 por minuto usa Retry-After; el diario no ofrece reintentar", () => {
    const minuto = describirError(new ApiError(429, "Demasiadas solicitudes con IA en poco tiempo", 42));
    expect(minuto).toMatchObject({ tipo: "limite", esperaSeg: 42, reintentable: true });
    const diario = describirError(new ApiError(429, "Presupuesto diario de IA agotado"));
    expect(diario).toMatchObject({ tipo: "limite", reintentable: false });
  });
  it("distingue 403, 401 y red caída", () => {
    expect(describirError(new ApiError(403, "Solo admin")).tipo).toBe("permiso");
    expect(describirError(new ApiError(401, "x")).tipo).toBe("sesion");
    expect(describirError(new TypeError("Failed to fetch")).tipo).toBe("red");
  });
});

describe("MarkdownLite", () => {
  it("renderiza listas, tablas y negrita sin interpretar HTML", () => {
    const { container } = render(<MarkdownLite texto={"Hola **mundo** <b>x</b>\n\n- uno\n- dos\n\n| A | B |\n|---|---|\n| 1 | 2 |"} />);
    expect(screen.getByText("mundo").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(container.querySelector("b")).toBeNull();
  });
});
