// Cliente HTTP al backend real de Laplace (FastAPI, backend/api/). SPA pura — todo fetch()
// va directo al backend, sin proxy server-side propio (la web no tiene servidor). Los
// endpoints de solo-lectura (partidos, predicción, simulador) no llevan ningún secreto — un
// secreto en JS del navegador es público por definición, así que nunca se usa `x-kairos-key`
// acá (eso es solo para la app móvil compilada). Lo que sí requiere identidad usa el JWT de
// `/api/v1/auth/login` vía el header Authorization.

// Compilada (producción) la web la sirve el propio backend (backend/api/web_estatico.py): la API está en el MISMO origen y el
// agente en el puerto 9100 del mismo equipo, así funciona igual abierta desde otra PC o el celular de la red. En desarrollo
// (`pnpm dev`, puerto 9002) se apunta a 127.0.0.1. Las variables VITE_* siempre mandan.
const ES_PRODUCCION = import.meta.env.PROD && typeof window !== "undefined";
const BASE_URL = import.meta.env.VITE_KAIROS_BACKEND_URL ?? (ES_PRODUCCION ? window.location.origin : "http://127.0.0.1:9001");
export const AGENT_URL = import.meta.env.VITE_LAPLACE_AGENT_URL ?? (ES_PRODUCCION ? `${window.location.protocol}//${window.location.hostname}:9100` : "http://127.0.0.1:9100");

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** Segundos indicados por el header Retry-After (429), si el backend lo envió. */
    public retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  return requestAt(BASE_URL, path, options);
}

export async function requestAt<T>(baseUrl: string, path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem("laplace_web_token");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${baseUrl}${path}`, { ...options, headers });
  if (!res.ok) {
    let mensaje = `Error ${res.status}`;
    try {
      const body = await res.json();
      mensaje = body.detail ?? mensaje;
    } catch {
      // respuesta sin JSON — nos quedamos con el mensaje genérico
    }
    const espera = Number(res.headers.get("Retry-After"));
    throw new ApiError(res.status, mensaje, Number.isFinite(espera) && espera > 0 ? espera : undefined);
  }
  return res.json() as Promise<T>;
}
