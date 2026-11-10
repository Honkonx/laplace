import { FormEvent, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api";

const MODELOS_INICIALES: Record<string, string> = {
  gemini: "gemini-2.5-flash",
  groq: "openai/gpt-oss-120b",
  openrouter: "nvidia/nemotron-3-super-120b-a12b:free",
  ollama_cloud: "gpt-oss:120b",
  claude: "claude-sonnet-4-5",
};

export function AdminIA() {
  const [estado, setEstado] = useState<Awaited<ReturnType<typeof api.obtenerProveedoresIaAdmin>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [provider, setProvider] = useState("gemini");
  const [model, setModel] = useState(MODELOS_INICIALES.gemini);
  const [apiKey, setApiKey] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const reload = () => void api.obtenerProveedoresIaAdmin().then(setEstado).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "No se pudo cargar IA"));
  useEffect(reload, []);
  const ollama = useMemo(() => estado?.proveedores.find((item) => item.id === "ollama_cloud"), [estado]);

  function seleccionarProveedor(value: string) {
    setProvider(value);
    setModel(MODELOS_INICIALES[value] ?? "");
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(null); setNotice(null);
    try {
      const result = await api.configurarProveedorIaAdmin(provider, apiKey, model);
      setApiKey(""); setNotice(result.message); reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo guardar la configuración");
    } finally { setSaving(false); }
  }

  return <section className="panel p-5">
    <h2 className="text-lg">Control de IA</h2>
    <p className="mt-2 text-sm text-text-muted">La clave viaja una vez al backend autenticado, se guarda sólo en <code>.env</code> y nunca vuelve a aparecer en pantalla, chat, memoria o base de datos.</p>
    {error && <p role="alert" className="mt-4 text-sm text-conf-baja">{error}</p>}
    {notice && <p className="mt-4 rounded-lg border border-conf-alta/50 p-3 text-sm text-conf-alta">{notice}</p>}
    {estado && <>
      <p className="mt-4 text-sm">Runtime de IA: <strong>{estado.agent_ia_activa ? "activo" : "inactivo"}</strong></p>
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {estado.proveedores.map((item) => <div key={item.id} className="rounded-lg bg-surface-light p-3">
          <p className="font-medium">{item.id === "ollama_cloud" ? "Ollama Cloud" : item.id}</p>
          <p className="mt-1 text-xs text-text-muted">{item.modelo}</p>
          <p className={`mt-2 text-xs ${item.configurado ? "text-conf-alta" : "text-text-dim"}`}>{item.configurado ? "Clave configurada" : "Sin clave"}</p>
        </div>)}
      </div>
    </>}
    <form onSubmit={submit} className="mt-6 grid gap-3 border-t border-border pt-5 sm:grid-cols-2">
      <label className="text-sm">Proveedor
        <select value={provider} onChange={(event) => seleccionarProveedor(event.target.value)} className="field mt-1">
          <option value="gemini">Google Gemini</option><option value="groq">Groq</option><option value="openrouter">OpenRouter</option><option value="ollama_cloud">Ollama Cloud</option><option value="claude">Anthropic</option>
        </select>
      </label>
      <label className="text-sm">Modelo
        <input list={provider === "ollama_cloud" ? "modelos-ollama-cloud" : undefined} value={model} onChange={(event) => setModel(event.target.value)} className="field mt-1" required />
        {provider === "ollama_cloud" && <><datalist id="modelos-ollama-cloud">{ollama?.modelos_sugeridos?.map((nombre) => <option key={nombre} value={nombre} />)}</datalist><span className="mt-1 block text-xs text-text-muted">Cloud solamente. Elige uno sugerido o escribe un modelo habilitado por tu cuenta.</span></>}
      </label>
      <label className="text-sm sm:col-span-2">Clave API<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Se guarda sólo en .env" className="field mt-1" required /></label>
      <div className="sm:col-span-2"><button disabled={saving} className="btn btn-primary">{saving ? "Guardando…" : "Guardar y reiniciar luego"}</button></div>
    </form>
  </section>;
}
