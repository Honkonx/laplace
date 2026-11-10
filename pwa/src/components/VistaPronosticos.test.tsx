import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ControlVista, EsqueletosCarga, EstadoVacio } from "./VistaPronosticos";

describe("ControlVista", () => {
  it("muestra los conteos, marca la vista activa y avisa el cambio", () => {
    const onChange = vi.fn();
    render(<ControlVista vista="con" conteo={{ con: 3, todos: 10 }} onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Con pronóstico (3)" })).toHaveAttribute("aria-pressed", "true");
    const todos = screen.getByRole("button", { name: "Todos (10)" });
    expect(todos).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(todos);
    expect(onChange).toHaveBeenCalledWith("todos");
  });
});

describe("EstadoVacio", () => {
  it("ofrece ver todos los partidos", () => {
    const onVerTodos = vi.fn();
    render(<EstadoVacio onVerTodos={onVerTodos} />);
    fireEvent.click(screen.getByRole("button", { name: "Ver todos los partidos" }));
    expect(onVerTodos).toHaveBeenCalledOnce();
  });
});

describe("EsqueletosCarga", () => {
  it("marca el contenedor como ocupado", () => {
    const { container } = render(<EsqueletosCarga />);
    expect(container.firstElementChild).toHaveAttribute("aria-busy", "true");
  });
});
