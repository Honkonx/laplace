import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SinPronostico } from "./SinPronostico";

const referencia = { nivel: "liga" as const, pct_local: 44.6, pct_empate: 26.2, pct_visitante: 29.2 };

describe("SinPronostico", () => {
  it("muestra los motivos, la referencia redondeada y el aviso, sin Pick", () => {
    const { container } = render(
      <SinPronostico motivos={["Sin histórico del local", "Sin cuotas"]} referencia={referencia} />,
    );
    expect(screen.getByText("Sin histórico del local")).toBeInTheDocument();
    expect(screen.getByText("Sin cuotas")).toBeInTheDocument();
    expect(screen.getByText(/Referencia, no pronóstico/)).toBeInTheDocument();
    expect(screen.getByText(/esta liga/)).toBeInTheDocument();
    expect(screen.getByText("45%")).toBeInTheDocument();
    expect(screen.getByText("26%")).toBeInTheDocument();
    expect(screen.getByText("29%")).toBeInTheDocument();
    expect(container.textContent).toContain("No distingue a estos dos equipos");
    expect(container.textContent).not.toMatch(/Pick/);
  });

  it("rotula el promedio general cuando la liga no está cubierta", () => {
    render(<SinPronostico motivos={["x"]} referencia={{ ...referencia, nivel: "general" }} />);
    expect(screen.getByText(/promedio general/)).toBeInTheDocument();
  });

  it("muestra solo 3 motivos y omite la referencia si no hay datos", () => {
    render(<SinPronostico motivos={["a", "b", "c", "d"]} />);
    expect(screen.queryByText("d")).not.toBeInTheDocument();
    expect(screen.queryByText(/Referencia/)).not.toBeInTheDocument();
  });
});
