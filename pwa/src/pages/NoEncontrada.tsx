import { Link } from "react-router-dom";

/** Cualquier dirección que no existe: antes la página quedaba en blanco (H-017, 2026-11-12). */
export function NoEncontrada() {
  return (
    <section className="mx-auto max-w-xl py-16 text-center">
      <h1 className="text-2xl font-semibold">No encontramos esa página</h1>
      <p className="mt-2 text-text-muted">La dirección no existe o cambió.</p>
      <Link to="/" className="btn btn-primary mt-6 inline-flex items-center justify-center">Ir a los partidos</Link>
    </section>
  );
}
