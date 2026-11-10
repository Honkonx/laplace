import { useEffect, useState } from "react";
import { obtenerPartidos, type Liga, ApiError } from "@/lib/api";
import { PartidoCard } from "@/components/PartidoCard";

function aYyyymmdd(fecha: Date): string {
  return `${fecha.getFullYear()}${String(fecha.getMonth() + 1).padStart(2, "0")}${String(fecha.getDate()).padStart(2, "0")}`;
}

function aInputDate(fecha: Date): string {
  return `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, "0")}-${String(fecha.getDate()).padStart(2, "0")}`;
}

function etiquetaFecha(fecha: Date): string {
  return fecha.toLocaleDateString("es-CL", { weekday: "long", day: "numeric", month: "long" });
}

// Calendario — navegar partidos de CUALQUIER fecha (no solo hoy/mañana como el toggle rápido
// de Home). Mismo endpoint (`GET /api/v1/partidos?fecha=`), mismo PartidoCard — solo cambia
// cómo se elige la fecha: flechas prev/next día + selector nativo `<input type="date">` (sin
// agregar una librería de date-picker para esto — YAGNI).
export function Calendario() {
  const [fecha, setFecha] = useState(new Date());
  const [ligas, setLigas] = useState<Liga[] | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fechaStr = aYyyymmdd(fecha);

  useEffect(() => {
    setCargando(true);
    setError(null);
    obtenerPartidos(fechaStr)
      .then((r) => setLigas(r.Stages))
      .catch((e) => setError(e instanceof ApiError ? e.message : "No se pudieron cargar los partidos."))
      .finally(() => setCargando(false));
  }, [fechaStr]);

  function moverDia(delta: number) {
    setFecha((actual) => {
      const nueva = new Date(actual);
      nueva.setDate(nueva.getDate() + delta);
      return nueva;
    });
  }

  const ligasConPartidos = (ligas ?? [])
    .map((liga) => ({ ...liga, Events: liga.Events.filter((e) => e.Eps === "NS") }))
    .filter((liga) => liga.Events.length > 0);

  return (
    <div className="space-y-5 pt-1">
      <h1 className="font-display text-2xl font-bold tracking-tight">Calendario</h1>

      <div className="flex items-center gap-2 rounded-xl bg-surface p-2">
        <button
          onClick={() => moverDia(-1)}
          aria-label="Día anterior"
          className="flex h-9 w-9 flex-none items-center justify-center rounded-lg text-text-muted active:bg-surface-light"
        >
          ‹
        </button>
        <label className="flex-1 text-center">
          <span className="block text-sm font-medium capitalize text-text">{etiquetaFecha(fecha)}</span>
          <input
            type="date"
            value={aInputDate(fecha)}
            onChange={(e) => e.target.value && setFecha(new Date(`${e.target.value}T00:00:00`))}
            className="mt-0.5 bg-transparent text-center font-mono text-[11px] text-text-dim outline-none"
          />
        </label>
        <button
          onClick={() => moverDia(1)}
          aria-label="Día siguiente"
          className="flex h-9 w-9 flex-none items-center justify-center rounded-lg text-text-muted active:bg-surface-light"
        >
          ›
        </button>
      </div>

      {cargando && <p className="text-text-muted">Cargando partidos…</p>}
      {error && <p className="text-conf-baja">{error}</p>}
      {!cargando && !error && ligasConPartidos.length === 0 && (
        <p className="text-text-muted">No hay partidos programados para esta fecha.</p>
      )}

      <div className="space-y-6">
        {ligasConPartidos.map((liga, idx) => (
          <section key={`${liga.Snm ?? liga.CompN ?? "liga"}-${idx}`}>
            <h2 className="mb-2 px-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-text-dim">
              {liga.Snm ?? liga.CompN}
            </h2>
            <div className="flex flex-col gap-2.5">
              {liga.Events.map((evento) => (
                <PartidoCard key={evento.Eid} evento={evento} liga={liga.Snm ?? liga.CompN ?? ""} fecha={fechaStr} />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
