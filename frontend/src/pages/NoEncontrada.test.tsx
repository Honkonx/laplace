import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { NoEncontrada } from "@/pages/NoEncontrada";

describe("NoEncontrada", () => {
  it("una dirección que no existe muestra un aviso y un camino de vuelta, no una página en blanco", () => {
    render(
      <MemoryRouter initialEntries={["/laplace"]}>
        <Routes>
          <Route path="/" element={<p>inicio</p>} />
          <Route path="*" element={<NoEncontrada />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: /No encontramos esa página/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Ir a los partidos/i }).getAttribute("href")).toBe("/");
  });
});
