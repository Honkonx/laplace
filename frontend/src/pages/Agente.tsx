import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import * as api from "@/lib/api";
import { describirError, type ErrorAmigable } from "@/lib/errores";
import { nuevoId, SUGERENCIAS, type MensajeUI } from "@/lib/chat";
import { useUsoAgente } from "@/lib/useUsoAgente";
import { AvisoError } from "@/components/chat/AvisoError";
import { Composer } from "@/components/chat/Composer";
import { ListaSesiones } from "@/components/chat/ListaSesiones";
import { IndicadorEscritura, MensajeBurbuja, type EstadoValoracion } from "@/components/chat/MensajeBurbuja";
import { PanelOpciones } from "@/components/chat/PanelOpciones";

type Panel = "sesiones" | "opciones" | null;

function desdeHistorial(m: api.AgentMessage, i: number): MensajeUI {
  return { id: `h${i}-${m.created_at}`, role: m.role, content: m.content, modo: m.mode, creado: m.created_at };
}

export function Agente() {
  const { username, rol } = useAuth();
  const esAdmin = rol === "admin";
  const { uso, disponible: usoDisponible, recargar: recargarUso } = useUsoAgente(!!username);

  const [texto, setTexto] = useState("");
  const [usarIa, setUsarIa] = useState(true);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sesiones, setSesiones] = useState<api.AgentSession[]>([]);
  const [mensajes, setMensajes] = useState<MensajeUI[]>([]);
  const [variantes, setVariantes] = useState<api.PrediccionVarianteAgente[]>([]);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<ErrorAmigable | null>(null);
  const [ultimoEnviado, setUltimoEnviado] = useState<string | null>(null);
  const [valoraciones, setValoraciones] = useState<Record<string, EstadoValoracion>>({});
  const [panel, setPanel] = useState<Panel>(null);
  const finHilo = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!username) return;
    void api.obtenerPrediccionesAgente().then((d) => setVariantes(d.items)).catch(() => undefined);
    api.listarSesionesAgente()
      .then(async (d) => {
        setSesiones(d.sessions);
        const ultima = d.sessions[0];
        if (!ultima) return;
        const historial = await api.obtenerMensajesSesionAgente(ultima.id);
        setSessionId(ultima.id);
        setMensajes(historial.messages.map(desdeHistorial));
      })
      .catch((e: unknown) => setError(describirError(e)));
  }, [username]);

  // Sin cupo o sin proveedor, el modo IA se apaga solo en vez de fallar en cada mensaje.
  useEffect(() => {
    if (usoDisponible && uso && (uso.ia_disponible === false || (uso.restantes ?? 1) <= 0)) setUsarIa(false);
  }, [uso, usoDisponible]);

  useEffect(() => {
    finHilo.current?.scrollIntoView({ block: "end" });
  }, [mensajes, cargando, error]);

  async function abrirSesion(id: string) {
    setError(null);
    setPanel(null);
    try {
      const historial = await api.obtenerMensajesSesionAgente(id);
      setSessionId(id);
      setMensajes(historial.messages.map(desdeHistorial));
    } catch (e) {
      setError(describirError(e));
    }
  }

  function nuevaConversacion() {
    setSessionId(null);
    setMensajes([]);
    setError(null);
    setPanel(null);
  }

  const enviar = useCallback(async (contenido: string, repetir = false) => {
    const limpio = contenido.trim();
    if (!limpio || cargando) return;
    setError(null);
    setUltimoEnviado(limpio);
    if (!repetir) {
      setTexto("");
      setMensajes((previos) => [...previos, { id: nuevoId(), role: "user", content: limpio, creado: new Date().toISOString() }]);
    }
    setCargando(true);
    try {
      const r = await api.conversarConAgente(limpio, sessionId, usarIa);
      setSessionId(r.session_id);
      setMensajes((previos) => [...previos, { id: nuevoId(), role: "assistant", content: r.respuesta, modo: r.modo, herramienta: r.herramienta, runId: r.run_id, prediccion: r.prediccion, creado: new Date().toISOString() }]);
      void api.listarSesionesAgente().then((d) => setSesiones(d.sessions)).catch(() => undefined);
      void api.obtenerPrediccionesAgente().then((d) => setVariantes(d.items)).catch(() => undefined);
      if (usarIa) recargarUso();
    } catch (e) {
      setError(describirError(e));
    } finally {
      setCargando(false);
    }
  }, [cargando, sessionId, usarIa, recargarUso]);

  async function valorar(mensaje: MensajeUI, util: boolean) {
    if (!mensaje.runId) return;
    setValoraciones((v) => ({ ...v, [mensaje.id]: "enviando" }));
    try {
      await api.enviarFeedbackAgente({ run_id: mensaje.runId, rating: util ? 5 : 1, label: util ? "util" : "no_util" });
      setValoraciones((v) => ({ ...v, [mensaje.id]: util ? "util" : "no_util" }));
    } catch {
      setValoraciones((v) => ({ ...v, [mensaje.id]: "error" }));
    }
  }

  if (!username) {
    return (
      <section className="panel mx-auto max-w-lg p-6">
        <h1 className="text-xl">Laplace, el asistente</h1>
        <p className="mt-2 text-sm text-text-muted">Entra para conversar, guardar tu contexto y pedir análisis de partidos. Si faltan datos, Laplace lo dice en vez de inventar.</p>
        <Link to="/entrar" className="btn btn-primary mt-4">Entrar o crear cuenta</Link>
      </section>
    );
  }

  const asideBase = "flex-col bg-bg lg:static lg:flex lg:bg-transparent";
  const mostrarAside = (id: Exclude<Panel, null>) => (panel === id ? `absolute inset-0 z-10 flex ${asideBase}` : `hidden ${asideBase}`);

  return (
    <section className="relative grid h-[calc(100dvh-11rem)] min-h-[28rem] gap-3 md:h-[calc(100dvh-14rem)] lg:grid-cols-[15rem_minmax(0,1fr)_19rem]" aria-label="Conversación con Laplace">
      <aside className={`panel overflow-hidden ${mostrarAside("sesiones")}`} aria-label="Conversaciones">
        <ListaSesiones sesiones={sesiones} activa={sessionId} onAbrir={(id) => void abrirSesion(id)} onNueva={nuevaConversacion} />
        <button type="button" onClick={() => setPanel(null)} className="btn m-2 lg:hidden">Cerrar</button>
      </aside>

      <div className="panel flex min-h-0 flex-col overflow-hidden">
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2 lg:hidden">
          <button type="button" onClick={() => setPanel("sesiones")} className="btn btn-sm">Conversaciones</button>
          <button type="button" onClick={() => setPanel("opciones")} className="btn btn-sm">Opciones</button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4" role="log" aria-live="polite" aria-label="Mensajes">
          {mensajes.length === 0 && !cargando && (
            <div className="mx-auto max-w-md pt-4">
              <h1 className="text-lg">¿Qué quieres saber hoy?</h1>
              <p className="mt-1 text-sm text-text-muted">Pregunta por partidos, ligas o pronósticos. Las cifras salen de los modelos del bot; la IA, cuando la activas, solo las redacta.</p>
              <ul className="mt-4 grid gap-2">
                {SUGERENCIAS.map((s) => (
                  <li key={s}><button type="button" onClick={() => void enviar(s)} className="btn w-full justify-start text-left font-normal">{s}</button></li>
                ))}
              </ul>
            </div>
          )}
          {mensajes.map((m, i) => <MensajeBurbuja key={m.id} mensaje={m} valoracion={valoraciones[m.id]} onValorar={(msg, util) => void valorar(msg, util)} onResponder={i === mensajes.length - 1 && !cargando ? (t) => void enviar(t) : undefined} />)}
          {cargando && <IndicadorEscritura />}
          {error && <AvisoError error={error} onReintentar={ultimoEnviado ? () => void enviar(ultimoEnviado, true) : undefined} onSeguirSinIa={() => { setUsarIa(false); setError(null); }} />}
          <div ref={finHilo} />
        </div>

        <Composer valor={texto} onCambio={setTexto} onEnviar={() => void enviar(texto)} cargando={cargando} />
      </div>

      <aside className={`panel overflow-hidden ${mostrarAside("opciones")}`} aria-label="Opciones del agente">
        <div className="min-h-0 flex-1">
          <PanelOpciones usarIa={usarIa} onUsarIa={setUsarIa} esAdmin={esAdmin} uso={uso} usoDisponible={usoDisponible} variantes={variantes} />
        </div>
        <button type="button" onClick={() => setPanel(null)} className="btn m-2 lg:hidden">Cerrar</button>
      </aside>
    </section>
  );
}
