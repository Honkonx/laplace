import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GolesPorEquipo } from "./GolesPorEquipo";

const goles = {
  local: { esperados: 1.7, p0: 0.18, p1: 0.31, p2: 0.27, p3_o_mas: 0.24, marca: 0.82 },
  visitante: { esperados: 1.1, p0: 0.33, p1: 0.37, p2: 0.2, p3_o_mas: 0.1, marca: 0.67 },
  acierto_historico_marcador: 0.124,
};

describe("GolesPorEquipo", () => {
  it("muestra goles esperados, probabilidad de marcar, tramos y acierto del marcador", () => {
    const { container } = render(<GolesPorEquipo goles={goles} local="River" visitante="Boca" marcador="1-1" />);
    expect(screen.getByText("Goles por equipo")).toBeInTheDocument();
    expect(screen.getByText("River")).toBeInTheDocument();
    expect(screen.getByText("1.7")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument();
    expect(screen.getByText("1-1")).toBeInTheDocument();
    expect(container.textContent).toContain("acierta ~12 % de las veces");
    expect(container.textContent).toContain("Estimación propia; donde hay cuotas, la cuota es mejor guía.");
  });

  it("no renderiza nada sin el campo", () => {
    const { container } = render(<GolesPorEquipo goles={null} local="River" visitante="Boca" />);
    expect(container).toBeEmptyDOMElement();
    const otro = render(<GolesPorEquipo local="River" visitante="Boca" />);
    expect(otro.container).toBeEmptyDOMElement();
  });
});
