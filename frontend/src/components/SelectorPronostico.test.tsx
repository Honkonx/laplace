import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EstadoVacioPartidos } from "./EstadoVacioPartidos";
import { EsqueletoPartidos } from "./EsqueletoPartidos";
import { SelectorPronostico } from "./SelectorPronostico";

describe("SelectorPronostico", () => {
  it("muestra los conteos y marca la opción activa", () => {
    render(<SelectorPronostico modo="con" conteo={{ con: 3, total: 20 }} onCambiar={() => {}} />);
    expect(screen.getByRole("button", { name: "Con pronóstico (3)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Todos (20)" })).toHaveAttribute("aria-pressed", "false");
  });

  it("avisa el modo elegido al pulsar", () => {
    const onCambiar = vi.fn();
    render(<SelectorPronostico modo="con" conteo={{ con: 3, total: 20 }} onCambiar={onCambiar} />);
    fireEvent.click(screen.getByRole("button", { name: "Todos (20)" }));
    expect(onCambiar).toHaveBeenCalledWith("todos");
  });
});

describe("EstadoVacioPartidos", () => {
  it("ofrece ver todos cuando el filtro de pronóstico vació la lista", () => {
    const onVerTodos = vi.fn();
    render(<EstadoVacioPartidos porFiltroPronostico onVerTodos={onVerTodos} />);
    fireEvent.click(screen.getByRole("button", { name: "Ver todos los partidos" }));
    expect(onVerTodos).toHaveBeenCalledTimes(1);
  });

  it("sin filtro de pronóstico no muestra el botón", () => {
    render(<EstadoVacioPartidos porFiltroPronostico={false} onVerTodos={() => {}} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText("No hay partidos próximos con estos filtros.")).toBeInTheDocument();
  });
});

describe("EsqueletoPartidos", () => {
  it("dibuja la cantidad pedida de tarjetas sin texto", () => {
    const { container } = render(<EsqueletoPartidos tarjetas={2} />);
    expect(screen.getByTestId("esqueleto-partidos").children).toHaveLength(2);
    expect(container.textContent).toBe("");
  });
});
