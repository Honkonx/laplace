import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { describirError } from "@/lib/errores";
import {
  MAX_MERCADOS, MERCADOS, aceptarConsentimiento, borrarPerfil, cambiarAvisos, dejarDeSeguir,
  guardarPerfil, obtenerSeguimientos, seguir,
  type Estilo, type ResumenSeguimientos, type RespuestaSeguimientos,
} from "@/lib/seguimientos";

const ESTILOS: { valor: Estilo; etiqueta: string }[] = [
  { valor: "corto", etiqueta: "Corto" },
  { valor: "normal", etiqueta: "Normal" },
  { valor: "tecnico", etiqueta: "Técnico" },
];
const SIN_CONSENTIMIENTO = "Acepta primero para usar esto";
const TARJETA = "panel p-4";
const BOTON = "btn btn-sm";
const BOTON_PRIMARIO = "btn btn-primary btn-sm";
const CAMPO = "min-h-11 w-full rounded-lg border border-border bg-surface px-3 text-sm text-text outline-none focus:border-accent disabled:opacity-50";
const GRILLA = "grid gap-4 md:grid-cols-2";

type Tipo = "equipo" | "liga";

function FormularioSeguir({ tipo, etiqueta, ejemplo, deshabilitado, lleno, onSeguir }: {
  tipo: Tipo; etiqueta: string; ejemplo: string; deshabilitado: boolean; lleno: boolean;
  onSeguir: (tipo: Tipo, nombre: string) => Promise<boolean>;
}) {
  const [nombre, setNombre] = useState("");
  const largo = nombre.trim().length;
  const bloqueado = deshabilitado || lleno;
  const motivo = deshabilitado ? SIN_CONSENTIMIENTO : lleno ? "Llegaste al límite de tu plan" : undefined;
  async function enviar(e: FormEvent) {
    e.preventDefault();
    if (await onSeguir(tipo, nombre.trim())) setNombre("");
  }
  return (
    <form onSubmit={(e) => void enviar(e)} className="flex gap-2" aria-label={`Seguir ${tipo}`}>
      <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder={ejemplo} aria-label={etiqueta}
        maxLength={60} disabled={bloqueado} title={motivo} className={CAMPO} />
      <button type="submit" className={BOTON_PRIMARIO} disabled={bloqueado || largo < 3} title={motivo}>Seguir</button>
    </form>
  );
}

function Lista({ titulo, items, limite, deshabilitado, onQuitar }: {
  titulo: string; items: string[]; limite: number; deshabilitado: boolean; onQuitar: (n: string) => void;
}) {
  return (
    <div>
      <h2 className="flex items-baseline justify-between text-base">
        {titulo}<span className="num text-xs text-text-muted">{items.length} de {limite}</span>
      </h2>
      {items.length === 0 ? <p className="mt-2 text-sm text-text-dim">Nada por ahora</p> : (
        <ul className="mt-2 space-y-1.5">
          {items.map((n) => (
            <li key={n} className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate">{n}</span>
              <button type="button" className={BOTON} disabled={deshabilitado} onClick={() => onQuitar(n)}
                title={deshabilitado ? SIN_CONSENTIMIENTO : undefined} aria-label={`Dejar de seguir ${n}`}>Dejar de seguir</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PerfilSeguimiento({ resumen, deshabilitado, onGuardar, onBorrar }: {
  resumen: ResumenSeguimientos; deshabilitado: boolean;
  onGuardar: (p: { zona_horaria?: string; estilo?: Estilo; mercados?: string[] }) => void; onBorrar: () => void;
}) {
  const [zona, setZona] = useState(resumen.perfil.zona_horaria ?? "");
  const [estilo, setEstilo] = useState<Estilo | "">(resumen.perfil.estilo ?? "");
  const [mercados, setMercados] = useState<string[]>(resumen.perfil.mercados);
  const alternar = (m: string) =>
    setMercados((act) => (act.includes(m) ? act.filter((x) => x !== m) : act.length < MAX_MERCADOS ? [...act, m] : act));
  const guardar = (e: FormEvent) => {
    e.preventDefault();
    onGuardar({ ...(zona.trim() ? { zona_horaria: zona.trim() } : {}), ...(estilo ? { estilo } : {}), mercados });
  };
  const titulo = deshabilitado ? SIN_CONSENTIMIENTO : undefined;
  return (
    <form onSubmit={guardar} className="space-y-3" aria-label="Tu perfil">
      <h2 className="text-base">Tu perfil</h2>
      <label className="block text-sm">
        <span className="text-text-muted">Zona horaria</span>
        <input value={zona} onChange={(e) => setZona(e.target.value)} placeholder="Chile o America/Santiago"
          disabled={deshabilitado} title={titulo} className={`${CAMPO} mt-1`} />
      </label>
      <fieldset disabled={deshabilitado} title={titulo}>
        <legend className="text-sm text-text-muted">Estilo de respuesta</legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {ESTILOS.map((o) => (
            <label key={o.valor} className="flex items-center gap-1.5 text-sm">
              <input type="radio" name="estilo" value={o.valor} checked={estilo === o.valor} onChange={() => setEstilo(o.valor)} />
              {o.etiqueta}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset disabled={deshabilitado} title={titulo}>
        <legend className="text-sm text-text-muted">Mercados que te interesan</legend>
        <div className="mt-1 flex flex-wrap gap-3">
          {MERCADOS.map((m) => (
            <label key={m} className="flex items-center gap-1.5 text-sm">
              <input type="checkbox" checked={mercados.includes(m)} onChange={() => alternar(m)} />
              {m}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex gap-2">
        <button type="submit" className={BOTON_PRIMARIO} disabled={deshabilitado} title={titulo}>Guardar perfil</button>
        <button type="button" className={BOTON} disabled={deshabilitado} title={titulo} onClick={onBorrar}>Borrar perfil</button>
      </div>
    </form>
  );
}

export function Seguimientos() {
  const { username } = useAuth();
  const [resumen, setResumen] = useState<ResumenSeguimientos | null>(null);
  const [mensaje, setMensaje] = useState<{ texto: string; ok: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    obtenerSeguimientos().then(setResumen).catch((e: unknown) => setError(describirError(e).detalle));
  }, []);
  useEffect(() => { if (username) cargar(); }, [username, cargar]);

  async function ejecutar(accion: () => Promise<RespuestaSeguimientos>): Promise<boolean> {
    setOcupado(true);
    try {
      const { ok, mensaje: texto, ...nuevo } = await accion();
      setMensaje({ texto, ok });
      if (nuevo.equipos) setResumen((r) => (r ? { ...r, ...nuevo } : r));
      return ok;
    } catch (e) {
      setMensaje({ texto: describirError(e).detalle, ok: false });
      return false;
    } finally {
      setOcupado(false);
    }
  }

  if (!username) {
    return (
      <section className="panel mx-auto max-w-lg p-6">
        <h1 className="text-xl">Mis seguimientos</h1>
        <p className="mt-2 text-sm text-text-muted">Entra para seguir equipos y ligas.</p>
        <Link to="/entrar" className="btn btn-primary mt-4">Entrar</Link>
      </section>
    );
  }

  const sinConsentimiento = resumen ? !resumen.consentimiento : true;
  const bloqueado = sinConsentimiento || ocupado;

  return (
    <section className="space-y-4">
      <h1 className="text-2xl">Mis seguimientos</h1>
      {error && <p role="alert" className="rounded-lg border border-conf-baja/50 p-3 text-sm text-conf-baja">{error}</p>}
      {!resumen && !error && <p className="text-sm text-text-muted">Cargando…</p>}
      {resumen && (
        <>
          {sinConsentimiento && (
            <div className={`${TARJETA} flex items-center justify-between gap-3 text-sm`}>
              <span>Para guardar tus seguimientos y avisarte, acepta que Laplace los recuerde.</span>
              <button type="button" className={BOTON_PRIMARIO} disabled={ocupado}
                onClick={() => void ejecutar(aceptarConsentimiento)}>Aceptar</button>
            </div>
          )}
          {mensaje && (
            <p role="status" className={`text-sm ${mensaje.ok ? "text-conf-alta" : "text-conf-baja"}`}>{mensaje.texto}</p>
          )}
          {resumen.equipos.length === 0 && resumen.ligas.length === 0 && (
            <p className="text-sm text-text-muted">Todavía no sigues nada</p>
          )}
          <div className={GRILLA}>
            <div className={`${TARJETA} space-y-3`}>
              <Lista titulo="Equipos" items={resumen.equipos} limite={resumen.limites.equipos}
                deshabilitado={bloqueado} onQuitar={(n) => void ejecutar(() => dejarDeSeguir(n))} />
              <FormularioSeguir tipo="equipo" etiqueta="Nombre del equipo" ejemplo="Colo-Colo" deshabilitado={bloqueado}
                lleno={resumen.equipos.length >= resumen.limites.equipos} onSeguir={(t, n) => ejecutar(() => seguir(t, n))} />
            </div>
            <div className={`${TARJETA} space-y-3`}>
              <Lista titulo="Ligas" items={resumen.ligas} limite={resumen.limites.ligas}
                deshabilitado={bloqueado} onQuitar={(n) => void ejecutar(() => dejarDeSeguir(n))} />
              <FormularioSeguir tipo="liga" etiqueta="Nombre de la liga" ejemplo="Premier League" deshabilitado={bloqueado}
                lleno={resumen.ligas.length >= resumen.limites.ligas} onSeguir={(t, n) => ejecutar(() => seguir(t, n))} />
            </div>
          </div>
          <div className={`${TARJETA} flex items-center justify-between gap-3`}>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" role="switch" checked={resumen.avisos} disabled={bloqueado}
                title={sinConsentimiento ? SIN_CONSENTIMIENTO : undefined}
                onChange={(e) => void ejecutar(() => cambiarAvisos(e.target.checked))} />
              Avisos de partidos y resultados
            </label>
            <span className="num text-xs text-text-muted">Tope {resumen.limites.partidos_24h} partidos en 24 h</span>
          </div>
          <div className={TARJETA}>
            <PerfilSeguimiento key={JSON.stringify(resumen.perfil)} resumen={resumen} deshabilitado={bloqueado}
              onGuardar={(p) => void ejecutar(() => guardarPerfil(p))} onBorrar={() => void ejecutar(borrarPerfil)} />
          </div>
        </>
      )}
    </section>
  );
}
