import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProbabilidadBar } from "./ProbabilidadBar";

describe("ProbabilidadBar", () => {
  it("muestra los 3 porcentajes redondeados", () => {
    render(
      <ProbabilidadBar local="River" visitante="Boca" probLocal={0.552} probEmpate={0.25} probVisitante={0.198} />,
    );
    expect(screen.getByText("55%")).toBeInTheDocument();
    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();
  });
});
