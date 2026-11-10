import { useEffect, useMemo, useState } from "react";
import { ApiError, obtenerCatalogoPartidos, pedirPrediccion, type WebFixture, type WebLeague } from "@/lib/api";
import { useAuth } from "@/lib/AuthContext";
import { HeroBanner } from "@/components/HeroBanner";
import { TelegramCard } from "@/components/TelegramCard";
import { ProbabilidadBar } from "@/components/ProbabilidadBar";
import { SinPronostico } from "@/components/SinPronostico";
import { ControlVista, EsqueletosCarga, EstadoVacio } from "@/components/VistaPronosticos";
import { agruparPorLiga, contar, filtrarPorVista, guardarVista, leerVistaGuardada, vistaPorDefecto, type Vista } from "@/lib/pronosticables";

function dateId(offset = 0) {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return `${date.getFullYear()}${String(date.getMonth() + 1).padStart(2, "0")}${String(date.getDate()).padStart(2, "0")}`;
}

function Crest({ src, name }: { src: string | null; name: string }) {
  return src
    ? <img src={src} alt={`Escudo ${name}`} className="h-7 w-7 object-contain" loading="lazy" />
    : <span className="grid h-7 w-7 place-items-center rounded-full bg-surface-light text-[10px]">{name.slice(0, 1)}</span>;
}

export function Home() {
  const { username } = useAuth();
  const [offset, setOffset] = useState(0);
  const [scope, setScope] = useState<"priority" | "all">("priority");
  const [query, setQuery] = useState("");
  const [league, setLeague] = useState("");
  const [fixtures, setFixtures] = useState<WebFixture[]>([]);
  const [leagues, setLeagues] = useState<WebLeague[]>([]);
  const [effectiveScope, setEffectiveScope] = useState("priority");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [vistaElegida, setVistaElegida] = useState<Vista | null>(() => leerVistaGuardada());
  const date = dateId(offset);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      obtenerCatalogoPartidos({ date, scope, league: league || undefined, q: query || undefined })
        .then((data) => {
          setFixtures(data.fixtures.filter((fixture) => fixture.status !== "FT").sort((a, b) => Number(!!b.pronosticable) - Number(!!a.pronosticable)));
          setLeagues(data.leagues);
          setEffectiveScope(data.scope);
        })
        .catch((reason: unknown) => setError(reason instanceof ApiError ? reason.message : "No se pudo cargar el catálogo."))
        .finally(() => setLoading(false));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [date, scope, league, query]);

  const visibleLeagues = useMemo(() => leagues.filter((item) => scope === "all" || item.priority), [leagues, scope]);
  const conteo = useMemo(() => contar(fixtures), [fixtures]);
  const vista = vistaPorDefecto(conteo, vistaElegida);
  const grupos = useMemo(() => agruparPorLiga(filtrarPorVista(fixtures, vista)), [fixtures, vista]);
  function elegirVista(nueva: Vista) { setVistaElegida(nueva); guardarVista(nueva); }
  return <div className="space-y-5 pt-1">
    <header><p className="text-sm text-text-muted">{username ? "Hola," : "Bienvenido"}</p><h1 className="font-display text-2xl font-bold">{username ?? "Pronóstico de fútbol"}</h1></header>
    <HeroBanner titulo="Fútbol con cobertura" subtitulo="Datos visibles, filtros simples y análisis responsable" />
    <TelegramCard />
    <section className="rounded-xl border border-border bg-surface p-2">
      <div className="grid grid-cols-4 gap-1">{[0, 1, 2, 3].map((day) => <button key={day} onClick={() => setOffset(day)} className={`min-h-11 rounded-lg py-2 text-xs ${offset === day ? "bg-accent text-white" : "text-text-muted"}`}>{day === 0 ? "Hoy" : day === 1 ? "Mañana" : `+${day}`}</button>)}</div>
      <div className="mt-2 flex gap-1"><button onClick={() => { setScope("priority"); setLeague(""); }} className={`min-h-11 flex-1 rounded-lg py-2 text-xs ${scope === "priority" ? "bg-surface-light text-text" : "text-text-muted"}`}>Relevantes</button><button onClick={() => { setScope("all"); setLeague(""); }} className={`min-h-11 flex-1 rounded-lg py-2 text-xs ${scope === "all" ? "bg-surface-light text-text" : "text-text-muted"}`}>Todas</button></div>
      <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar equipo, partido o liga" aria-label="Buscar partido" className="mt-2 min-h-11 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm outline-none focus:border-accent" />
      <select value={league} onChange={(event) => setLeague(event.target.value)} className="mt-2 min-h-11 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm"><option value="">Ligas visibles</option>{visibleLeagues.map((item) => <option key={`${item.id}-${item.name}`} value={item.id}>{item.name} ({item.count})</option>)}</select>
      {scope === "priority" && effectiveScope === "fallback" && <p className="mt-2 rounded-lg bg-orange-400/10 p-2 text-xs text-conf-media">Hoy no hay cobertura de ligas prioritarias. Se muestra un catálogo de respaldo.</p>}
    </section>
    {loading && <EsqueletosCarga />}
    {error && <p className="rounded-lg bg-red-500/10 p-3 text-sm text-conf-baja">{error}</p>}
    {!loading && !error && fixtures.length > 0 && <ControlVista vista={vista} conteo={conteo} onChange={elegirVista} />}
    {!loading && !error && fixtures.length === 0 && <p className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">No hay partidos para estos filtros. Prueba otra fecha o abre todas las ligas.</p>}
    {!loading && !error && fixtures.length > 0 && grupos.length === 0 && <EstadoVacio onVerTodos={() => elegirVista("todos")} />}
    {!loading && grupos.map((grupo) => <section key={grupo.id} className="space-y-3">
      <h2 className="flex items-baseline justify-between text-sm font-semibold"><span>{grupo.nombre}</span><span className="text-xs font-normal text-text-muted">{grupo.con} de {grupo.partidos.length} con pronóstico</span></h2>
      {grupo.partidos.map((fixture) => <FixtureCard key={fixture.id} fixture={fixture} />)}
    </section>)}
  </div>;
}

function FixtureCard({ fixture }: { fixture: WebFixture }) {
  const { username } = useAuth();
  const [result, setResult] = useState<Awaited<ReturnType<typeof pedirPrediccion>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  async function predict() {
    if (!username) { setError("Inicia sesión para guardar y consultar este análisis."); return; }
    setLoading(true); setError(null);
    try { setResult(await pedirPrediccion({ match_id: fixture.id, local: fixture.home.name, visitante: fixture.away.name, liga: fixture.league.name, fecha: fixture.date.replaceAll("-", "") })); }
    catch (reason) { setError(reason instanceof ApiError ? reason.message : "No se pudo calcular el análisis."); }
    finally { setLoading(false); }
  }
  const consenso = result?.consenso;
  const probs = consenso?.prob_ponderada
    ?? (result?.modulos?.historico?.ok
      ? {
          local: result.modulos.historico.prob_local,
          empate: result.modulos.historico.prob_empate,
          visitante: result.modulos.historico.prob_visitante,
        }
      : result?.modulos?.poisson?.ok
        ? {
            local: result.modulos.poisson.prob_local,
            empate: result.modulos.poisson.prob_empate,
            visitante: result.modulos.poisson.prob_visitante,
          }
        : null);
  const tienePronostico = Boolean(
    consenso &&
    consenso.total_modulos > 0 &&
    consenso.pick_final &&
    !consenso.pick_final.startsWith("Sin pronóstico") &&
    probs,
  );
  const quality = result?.calidad_datos;
  return <article className="rounded-xl border border-border bg-surface p-3">
    <div className="flex items-center gap-2 text-xs text-text-muted"><Crest src={fixture.league.logo} name={fixture.league.name} />{fixture.league.name}{fixture.pronosticable && <span className="ml-auto text-conf-alta" title="El bot tiene histórico de estos equipos">✔ con pronóstico</span>}</div>
    <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-center text-sm"><div className="flex flex-col items-center gap-1"><Crest src={fixture.home.logo} name={fixture.home.name} /><strong>{fixture.home.name}</strong></div><span className="text-text-dim">vs</span><div className="flex flex-col items-center gap-1"><Crest src={fixture.away.logo} name={fixture.away.name} /><strong>{fixture.away.name}</strong></div></div>
    <div className="mt-3 flex items-center justify-between border-t border-border pt-3"><span className="text-xs text-text-muted">{fixture.kickoff ?? "Horario por confirmar"}</span><button onClick={() => void predict()} disabled={loading} className="min-h-11 rounded-lg bg-accent px-4 py-2 text-xs font-medium text-white disabled:opacity-50">{loading ? "Calculando…" : "Analizar"}</button></div>
    {error && <p className="mt-3 text-xs text-conf-baja">{error}</p>}
    {result && <div className="mt-3 border-t border-border pt-3">{tienePronostico && probs ? <><ProbabilidadBar local={fixture.home.name} visitante={fixture.away.name} probLocal={probs.local} probEmpate={probs.empate} probVisitante={probs.visitante} /><p className="mt-2 text-sm">Pick: <strong>{result.consenso.pick_final}</strong> · {result.consenso.confianza_final}</p><p className="mt-1 text-xs text-text-muted">{result.consenso.detalle}</p></> : <SinPronostico motivos={result.motivos_sin_pronostico} referencia={result.referencia_tasa_base} detalle={quality?.reason || result.consenso?.detalle} fuentes={quality?.sources} />}</div>}
  </article>;
}
