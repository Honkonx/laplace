import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ApiError, borrarConexionAdmin, guardarConexionAdmin, guardarOrdenIaAdmin, obtenerConexionesAdmin, probarConexionAdmin,
  type ConexionAdmin, type ConexionesAdmin,
} from "@/lib/api";

type Estado = "ok" | "bad" | "warn";
interface Prueba { estado: Estado; detalle: string }

const GLIFO: Record<Estado, string> = { ok: "✓", bad: "✗", warn: "⚠" };
const COLOR: Record<Estado, string> = { ok: "text-conf-alta", bad: "text-conf-baja", warn: "text-conf-media" };
const NOMBRE_IA: Record<string, string> = { ollama_cloud: "Ollama Cloud", groq: "Groq", gemini: "Google Gemini", openrouter: "OpenRouter", claude: "Claude (Anthropic)" };

function mensajeDe(razon: unknown): string {
  return razon instanceof ApiError || razon instanceof Error ? razon.message : "No se pudo completar la acción";
}

export function AdminConexiones() {
  const [datos, setDatos] = useState<ConexionesAdmin | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [pruebas, setPruebas] = useState<Record<string, Prueba>>({});
  const [editando, setEditando] = useState<string | null>(null);
  const [clave, setClave] = useState("");
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [pendienteCoste, setPendienteCoste] = useState<{ id: string; coste: string; accion: "probar" | "guardar" } | null>(null);
  const [borrando, setBorrando] = useState<string | null>(null);
  const [ordenIa, setOrdenIa] = useState<string[]>([]);

  const recargar = useCallback(() => {
    obtenerConexionesAdmin().then((d) => { setDatos(d); setOrdenIa(d.orden_ia); }).catch((r) => setError(mensajeDe(r)));
  }, []);
  useEffect(recargar, [recargar]);

  async function probar(c: ConexionAdmin, confirmar = false) {
    setOcupado(c.id); setError(null); setPendienteCoste(null);
    try {
      const r = await probarConexionAdmin(c.id, confirmar);
      if (r.requiere_confirmacion) { setPendienteCoste({ id: c.id, coste: r.coste ?? "", accion: "probar" }); return; }
      setPruebas((p) => ({ ...p, [c.id]: { estado: r.estado, detalle: r.detalle } }));
    } catch (razon) { setError(mensajeDe(razon)); } finally { setOcupado(null); }
  }

  async function probarTodas() {
    for (const c of datos?.conexiones ?? []) {
      if (c.configurada && !c.cobra_por_llamada && !c.cuesta) await probar(c);
    }
  }

  async function guardar(event: FormEvent, c: ConexionAdmin, confirmar = false) {
    event.preventDefault();
    setOcupado(c.id); setError(null); setAviso(null); setPendienteCoste(null);
    try {
      const r = await guardarConexionAdmin(c.id, clave, confirmar);
      setClave(""); setEditando(null); setAviso(`${c.nombre}: ${r.message}`);
      if (r.estado) setPruebas((p) => ({ ...p, [c.id]: { estado: r.estado as Estado, detalle: r.detalle } }));
      recargar();
    } catch (razon) { setError(mensajeDe(razon)); } finally { setOcupado(null); }
  }

  async function borrar(c: ConexionAdmin) {
    setOcupado(c.id); setError(null); setBorrando(null);
    try {
      const r = await borrarConexionAdmin(c.id);
      setAviso(`${c.nombre}: ${r.message}`); setPruebas((p) => { const { [c.id]: _quitada, ...resto } = p; return resto; }); recargar();
    } catch (razon) { setError(mensajeDe(razon)); } finally { setOcupado(null); }
  }

  function mover(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= ordenIa.length) return;
    setOrdenIa((o) => { const copia = [...o]; [copia[i], copia[j]] = [copia[j], copia[i]]; return copia; });
  }

  async function guardarOrden() {
    setError(null); setAviso(null);
    try { setAviso((await guardarOrdenIaAdmin(ordenIa)).message); recargar(); } catch (razon) { setError(mensajeDe(razon)); }
  }

  if (!datos) return <p className="text-text-muted">{error ?? "Cargando conexiones…"}</p>;
  const ia = datos.conexiones.filter((c) => c.grupo === "ia");

  return (
    <section className="space-y-5" aria-label="Conexiones externas">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg">Conexiones</h2>
          <p className="mt-1 text-sm text-text-muted">APIs de datos, IA y Telegram: se prueban antes de guardarse y la clave no vuelve a mostrarse.</p>
        </div>
        <button type="button" className="btn" onClick={() => void probarTodas()} disabled={ocupado !== null}>Probar todas (gratis)</button>
      </div>

      {datos.faltantes.length > 0 && (
        <p role="status" className="rounded-lg border border-conf-media/50 p-3 text-sm text-conf-media">Para tener pronósticos falta: {datos.faltantes.join("; ")}.</p>
      )}
      {error && <p role="alert" className="rounded-lg border border-conf-baja/50 p-3 text-sm text-conf-baja">{error}</p>}
      {aviso && <p role="status" className="rounded-lg border border-conf-alta/50 p-3 text-sm text-conf-alta">{aviso}</p>}

      {datos.grupos.map((g) => (
        <div key={g.id} className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-text-dim">{g.titulo}{g.nota && <span className="ml-2 font-normal normal-case text-text-dim">— {g.nota}</span>}</h3>
          <div className="grid gap-3 md:grid-cols-2">
            {datos.conexiones.filter((c) => c.grupo === g.id).map((c) => {
              const prueba = pruebas[c.id];
              const estado: Estado = prueba?.estado ?? (c.configurada ? "ok" : "bad");
              const texto = prueba?.detalle ?? (c.configurada ? "configurada (sin probar)" : "sin clave");
              return (
                <article key={c.id} className="panel space-y-2 p-4" aria-label={c.nombre}>
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="font-medium"><span className="num mr-2 text-text-dim">{c.numero}</span>{c.nombre}{c.destacada && <span className="ml-2 text-xs text-conf-media">lo principal</span>}</h4>
                    <span className={`text-sm ${COLOR[estado]}`}>{GLIFO[estado]} {texto}</span>
                  </div>
                  <p className="text-xs text-text-muted">{c.sirve}. Plan: {c.plan}.</p>
                  <p className="text-xs text-text-dim">Se guarda como <code>{c.variable}</code></p>
                  <div className="flex flex-wrap gap-2 pt-1">
                    <button type="button" className="btn btn-primary btn-sm" onClick={() => { setEditando(editando === c.id ? null : c.id); setClave(""); }}>{c.configurada ? "Cambiar clave" : "Poner clave"}</button>
                    {c.configurada && <button type="button" className="btn btn-sm" disabled={ocupado === c.id} onClick={() => void probar(c)}>{ocupado === c.id ? "Probando…" : "Probar"}</button>}
                    <a className="btn btn-sm" href={c.enlace} target="_blank" rel="noreferrer">Conseguir clave ↗</a>
                    {c.configurada && (borrando === c.id
                      ? <><button type="button" className="btn btn-sm text-conf-baja" onClick={() => void borrar(c)}>Sí, borrar</button><button type="button" className="btn btn-sm" onClick={() => setBorrando(null)}>No</button></>
                      : <button type="button" className="btn btn-sm" onClick={() => setBorrando(c.id)}>Borrar</button>)}
                  </div>
                  {pendienteCoste?.id === c.id && (
                    <p className="text-xs text-conf-media">Esta prueba cuesta {pendienteCoste.coste}.{" "}
                      <button type="button" className="underline" onClick={() => void probar(c, true)}>Probar igual</button></p>
                  )}
                  {editando === c.id && (
                    <form onSubmit={(e) => void guardar(e, c)} className="grid gap-2 border-t border-border pt-3">
                      <label className="text-sm">Clave
                        <input type="password" autoComplete="off" value={clave} onChange={(e) => setClave(e.target.value)} className="field mt-1" aria-label={`Clave de ${c.nombre}`} />
                      </label>
                      <p className="text-xs text-text-dim">Se prueba contra {c.host} antes de guardarse{c.cobra_por_llamada || c.cuesta ? ` (esta prueba cuesta ${c.cuesta ?? "1 llamada de tu cuota"}: se guarda sin probar)` : ""}.</p>
                      <div><button disabled={ocupado === c.id || clave.length < 8} className="btn btn-primary btn-sm">{ocupado === c.id ? "Guardando…" : "Guardar"}</button></div>
                    </form>
                  )}
                </article>
              );
            })}
          </div>
        </div>
      ))}

      <div className="panel space-y-3 p-4">
        <h3 className="font-medium">Orden de la IA</h3>
        <p className="text-xs text-text-muted">Se usa la primera que responda; las que no tienen clave se saltan solas.</p>
        <ol className="space-y-1">
          {ordenIa.map((id, i) => {
            const conexion = ia.find((c) => c.id === id);
            return (
              <li key={id} className="flex items-center justify-between gap-2 text-sm">
                <span><span className="num mr-2 text-text-dim">{i + 1}º</span>{NOMBRE_IA[id] ?? id}{conexion && !conexion.configurada && <span className="ml-2 text-xs text-text-dim">sin clave</span>}</span>
                <span className="flex gap-1">
                  <button type="button" className="btn btn-sm" aria-label={`Subir ${NOMBRE_IA[id] ?? id}`} onClick={() => mover(i, -1)} disabled={i === 0}>↑</button>
                  <button type="button" className="btn btn-sm" aria-label={`Bajar ${NOMBRE_IA[id] ?? id}`} onClick={() => mover(i, 1)} disabled={i === ordenIa.length - 1}>↓</button>
                </span>
              </li>
            );
          })}
        </ol>
        <button type="button" className="btn btn-primary btn-sm" onClick={() => void guardarOrden()}>Guardar orden</button>
      </div>
      <p className="text-xs text-text-dim">{datos.nota}</p>
    </section>
  );
}
