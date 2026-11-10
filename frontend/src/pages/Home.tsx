import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { ApiError, obtenerCatalogoPartidos, type WebFixture, type WebLeague } from "@/lib/api";
import { Escudo } from "@/components/Escudo";
import { PrediccionCard } from "@/components/PrediccionCard";
import { SelectorPronostico } from "@/components/SelectorPronostico";
import { EstadoVacioPartidos } from "@/components/EstadoVacioPartidos";
import { EsqueletoPartidos } from "@/components/EsqueletoPartidos";
import { contarPronosticables, filtrarPorModo, guardarModo, leerModoGuardado, modoPorDefecto, pronosticablesPrimero, type ModoPronostico } from "@/lib/pronosticables";

// Fecha local (no UTC): de noche en Chile toISOString() ya devuelve el día siguiente.
function isoLocal(fecha: Date): string {
  return `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, "0")}-${String(fecha.getDate()).padStart(2, "0")}`;
}

function fechaEnDias(offset: number): Date {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d;
}

const ATAJOS_FECHA = [
  { offset: 0, etiqueta: "Hoy" },
  { offset: 1, etiqueta: "Mañana" },
  { offset: 2, etiqueta: "Pasado" },
];

function agruparPorLiga(fixtures: WebFixture[]): Array<{ liga: WebFixture["league"]; partidos: WebFixture[] }> {
  const grupos = new Map<string, { liga: WebFixture["league"]; partidos: WebFixture[] }>();
  for (const f of fixtures) {
    const clave = `${f.league.id}|${f.league.name}`;
    const grupo = grupos.get(clave) ?? { liga: f.league, partidos: [] };
    grupo.partidos.push(f);
    grupos.set(clave, grupo);
  }
  return [...grupos.values()];
}

export function Home() {
  const [fechaIso, setFechaIso] = useState(() => isoLocal(fechaEnDias(0)));
  const [scope, setScope] = useState<"priority" | "all">("priority");
  const [q, setQ] = useState("");
  const [liga, setLiga] = useState("");
  const [fixtures, setFixtures] = useState<WebFixture[]>([]);
  const [ligas, setLigas] = useState<WebLeague[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modoElegido, setModoElegido] = useState<ModoPronostico | null>(() => leerModoGuardado());

  const fecha = fechaIso.replaceAll("-", "");

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setCargando(true);
      setError(null);
      obtenerCatalogoPartidos({ date: fecha, scope, league: liga || undefined, q: q || undefined })
        .then((r) => { setFixtures(r.fixtures); setLigas(r.leagues); })
        .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "No se pudo cargar el catálogo. Revisa tu conexión."))
        .finally(() => setCargando(false));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [fecha, scope, liga, q]);

  const { username } = useAuth();
  const ligasVisibles = useMemo(() => ligas.filter((l) => scope === "all" || l.priority), [ligas, scope]);
  const proximos = useMemo(() => fixtures.filter((f) => f.status !== "FT"), [fixtures]);
  const conteo = useMemo(() => contarPronosticables(proximos), [proximos]);
  const modo = modoPorDefecto(conteo, modoElegido);
  const visibles = useMemo(() => filtrarPorModo(proximos, modo), [proximos, modo]);
  const grupos = useMemo(() => agruparPorLiga(visibles), [visibles]);

  function elegirModo(nuevo: ModoPronostico) {
    setModoElegido(nuevo);
    guardarModo(nuevo);
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl">Partidos</h1>
          <p className="mt-1 text-sm text-text-muted">
            {cargando ? "Buscando partidos…" : `${visibles.length} ${visibles.length === 1 ? "partido" : "partidos"} en ${grupos.length} ${grupos.length === 1 ? "liga" : "ligas"} · hora de Chile`}
          </p>
        </div>
      </div>

      <SelectorPronostico modo={modo} conteo={conteo} onCambiar={elegirModo} />

      {!username && !cargando && visibles.length > 0 && (
        <p className="text-sm text-text-muted"><Link to="/entrar" className="font-medium text-accent underline underline-offset-2">Entra</Link> para pedir el pronóstico de cualquier partido.</p>
      )}

      <section aria-label="Filtros" className="panel space-y-3 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1" role="group" aria-label="Fecha">
            {ATAJOS_FECHA.map((a) => {
              const activo = fechaIso === isoLocal(fechaEnDias(a.offset));
              return (
                <button key={a.offset} type="button" aria-pressed={activo} onClick={() => setFechaIso(isoLocal(fechaEnDias(a.offset)))}
                  className={`btn ${activo ? "btn-primary" : ""}`}>{a.etiqueta}</button>
              );
            })}
          </div>
          <label className="sr-only" htmlFor="fecha-partidos">Elegir fecha</label>
          <input id="fecha-partidos" type="date" value={fechaIso} onChange={(e) => e.target.value && setFechaIso(e.target.value)} className="field min-w-0 !w-auto" />
          <div className="flex gap-1 sm:ml-auto" role="group" aria-label="Alcance de ligas">
            <button type="button" aria-pressed={scope === "priority"} onClick={() => { setScope("priority"); setLiga(""); }} className={`btn ${scope === "priority" ? "btn-primary" : ""}`}>Relevantes</button>
            <button type="button" aria-pressed={scope === "all"} onClick={() => { setScope("all"); setLiga(""); }} className={`btn ${scope === "all" ? "btn-primary" : ""}`}>Todas</button>
          </div>
        </div>
        <div className="grid gap-2 sm:grid-cols-[1fr_16rem]">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Buscar liga, equipo o partido" aria-label="Buscar partido" className="field" />
          <select value={liga} onChange={(e) => setLiga(e.target.value)} aria-label="Filtrar por liga" className="field">
            <option value="">Todas las ligas visibles</option>
            {ligasVisibles.map((l) => <option key={`${l.id}-${l.name}`} value={l.id}>{l.name} ({l.count})</option>)}
          </select>
        </div>
      </section>

      {error && <p role="alert" className="rounded-lg border border-conf-baja/50 p-3 text-sm text-conf-baja">{error}</p>}

      <div aria-busy={cargando} className="space-y-5">
      {cargando && <EsqueletoPartidos />}

      {!cargando && !error && visibles.length === 0 && (
        <EstadoVacioPartidos porFiltroPronostico={modo === "con" && proximos.length > 0} onVerTodos={() => elegirModo("todos")} />
      )}

      {!cargando && grupos.map(({ liga: l, partidos }) => (
        <section key={`${l.id}-${l.name}`} aria-label={l.name} className="space-y-2">
          <h2 className="flex items-center gap-2 text-sm font-medium text-text-muted">
            <Escudo src={l.logo} nombre={l.name} tamano="h-4 w-4" />
            {l.name}
            <span className="num text-text-dim">{contarPronosticables(partidos).con} de {partidos.length} con pronóstico</span>
          </h2>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {pronosticablesPrimero(partidos).map((f) => (
              <PrediccionCard key={f.id} mostrarLiga={false} partido={{
                matchId: f.id, liga: f.league.name, local: f.home.name, visitante: f.away.name, fecha: f.date.replaceAll("-", ""),
                hora: f.kickoff, pronosticable: f.pronosticable, ligaLogo: null, localLogo: f.home.logo, visitanteLogo: f.away.logo,
              }} />
            ))}
          </div>
        </section>
      ))}
      </div>
    </div>
  );
}
