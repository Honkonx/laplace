import { useEffect, useState } from "react";
import { obtenerEstadoScheduler, obtenerFuentesDeportivas, obtenerTrackRecord, type FuenteDeportiva, type JobScheduler } from "@/lib/api";
import { describirError } from "@/lib/errores";
import { useAuth } from "@/lib/AuthContext";

type Track = Awaited<ReturnType<typeof obtenerTrackRecord>>;

function Metrica({ etiqueta, valor, nota }: { etiqueta: string; valor: string; nota?: string }) {
  return (
    <div className="panel p-4">
      <p className="text-xs text-text-muted">{etiqueta}</p>
      <p className={`mt-1 font-medium ${/\d/.test(valor) ? "num text-2xl" : "text-xl text-text-muted"}`}>{valor}</p>
      {nota && <p className="mt-1 text-xs text-text-dim">{nota}</p>}
    </div>
  );
}

function edad(min: number | null): string {
  if (min == null) return "sin registro";
  if (min < 60) return `hace ${min} min`;
  if (min < 2880) return `hace ${Math.round(min / 60)} h`;
  return `hace ${Math.round(min / 1440)} días`;
}

function TrackRecord() {
  const [datos, setDatos] = useState<Track | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { obtenerTrackRecord().then(setDatos).catch((e: unknown) => setError(describirError(e).detalle)); }, []);

  if (error) return <p role="alert" className="text-sm text-conf-baja">{error}</p>;
  if (!datos) return <p className="text-sm text-text-muted">Cargando métricas…</p>;
  const evaluados = datos.volumen_real?.evaluados ?? datos.pick_final?.muestra ?? 0;
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Metrica etiqueta="Pronósticos evaluados" valor={String(evaluados)} nota="Con resultado real ya conocido" />
        <Metrica etiqueta="Acierto del pick" valor={datos.pick_final?.winrate == null ? "Sin muestra" : `${datos.pick_final.winrate}%`} />
        <Metrica etiqueta="RPS (menor es mejor)" valor={datos.rps.rps_promedio == null ? "Sin muestra" : String(datos.rps.rps_promedio)} nota={datos.rps.confiable ? undefined : "Muestra aún pequeña: no concluyente"} />
      </div>
      <div className="panel p-4 text-sm text-text-muted">
        <p>{datos.rps.nota}</p>
        {datos.advertencia_general && <p className="mt-2 text-conf-media">{datos.advertencia_general}</p>}
        <p className="mt-2 text-xs text-text-dim">Son métricas de pronósticos pasados, no una garantía sobre partidos futuros.</p>
      </div>
    </div>
  );
}

function SaludAdmin() {
  const [fuentes, setFuentes] = useState<FuenteDeportiva[] | null>(null);
  const [scheduler, setScheduler] = useState<{ corriendo: boolean; saludable: boolean; jobs: Record<string, JobScheduler> } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    obtenerFuentesDeportivas().then((r) => setFuentes(r.sources)).catch((e: unknown) => setError(describirError(e).detalle));
    obtenerEstadoScheduler().then((r) => setScheduler({ corriendo: r.scheduler_corriendo, saludable: r.saludable, jobs: r.jobs })).catch((e: unknown) => setError(describirError(e).detalle));
  }, []);

  return (
    <div className="space-y-6">
      {error && <p role="alert" className="text-sm text-conf-baja">{error}</p>}

      <section aria-labelledby="h-fuentes">
        <h2 id="h-fuentes" className="mb-2 text-base">Fuentes de datos</h2>
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[34rem] text-left text-sm">
            <thead><tr className="border-b border-border text-text-muted"><th className="px-3 py-2 font-medium">Fuente</th><th className="px-3 py-2 font-medium">Estado</th><th className="px-3 py-2 font-medium">Latencia</th><th className="px-3 py-2 font-medium">Última prueba</th></tr></thead>
            <tbody>
              {fuentes?.map((f) => (
                <tr key={f.id} className="border-b border-border last:border-0">
                  <td className="px-3 py-2"><span className="font-medium">{f.id}</span><span className="block text-xs text-text-dim">{f.role}</span></td>
                  <td className="px-3 py-2">{!f.configured ? <span className="text-text-muted">Sin credencial</span> : f.healthy == null ? <span className="text-text-muted">Sin probar</span> : f.healthy ? <span className="text-conf-alta">Responde</span> : <span className="text-conf-baja">Falla{f.detail ? ` · ${f.detail}` : ""}</span>}</td>
                  <td className="num px-3 py-2 text-text-muted">{f.latency_ms != null ? `${Math.round(f.latency_ms)} ms` : "—"}</td>
                  <td className="px-3 py-2 text-text-muted">{f.last_verified ? new Date(f.last_verified).toLocaleString("es-CL", { dateStyle: "short", timeStyle: "short" }) : "—"}</td>
                </tr>
              ))}
              {!fuentes && <tr><td colSpan={4} className="px-3 py-4 text-text-muted">Cargando…</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="h-sched">
        <h2 id="h-sched" className="mb-2 text-base">Tareas programadas</h2>
        {scheduler && (
          <>
            <p className="mb-2 text-sm">
              Programador: <strong className={scheduler.corriendo ? "text-conf-alta" : "text-conf-baja"}>{scheduler.corriendo ? "en marcha" : "detenido"}</strong>
              {" · "}<span className="text-text-muted">{scheduler.saludable ? "todas las tareas al día" : "hay tareas atrasadas"}</span>
            </p>
            <ul className="grid gap-2 md:grid-cols-2">
              {Object.entries(scheduler.jobs).map(([nombre, j]) => (
                <li key={nombre} className="panel p-3 text-sm">
                  <p className="font-medium">{nombre.replaceAll("_", " ")}</p>
                  <p className={j.atrasado ? "text-conf-baja" : "text-conf-alta"}>{j.estado === "nunca" ? "Nunca corrió" : j.atrasado ? "Atrasada" : "Al día"}</p>
                  <p className="text-xs text-text-muted">Último éxito: {edad(j.edad_minutos)}</p>
                </li>
              ))}
            </ul>
          </>
        )}
        {!scheduler && !error && <p className="text-sm text-text-muted">Cargando…</p>}
      </section>
    </div>
  );
}

export function EstadoBot() {
  const { rol } = useAuth();
  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-2xl">Estado y transparencia</h1>
        <p className="mt-1 max-w-2xl text-sm text-text-muted">Cuánto han acertado los pronósticos de Laplace con resultados reales. Si el número es malo, se muestra igual.</p>
      </div>
      <TrackRecord />
      {rol === "admin" && (
        <div className="space-y-2 border-t border-border pt-6">
          <h2 className="text-lg">Salud del sistema <span className="chip ml-1 align-middle">solo admin</span></h2>
          <SaludAdmin />
        </div>
      )}
    </section>
  );
}
