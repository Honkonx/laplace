import { request } from "./cliente";

// ---- Auth ----

export interface SesionUsuario {
  token: string;
  username: string;
  plan: string;
  // rol — 2026-09-10, separado de plan (ver backend/api/models/usuarios.py §v7). "admin" vivía
  // antes como pseudo-valor de `plan`; el backend ahora lo devuelve en su propio campo.
  rol: string;
}

export async function registrarse(username: string, password: string, termsAccepted: boolean) {
  return request<SesionUsuario>("/api/v1/auth/registro", {
    method: "POST",
    body: JSON.stringify({ username, password, origen: "web", terms_accepted: termsAccepted, terms_version: "2026-09-25" }),
  });
}

export async function iniciarSesion(username: string, password: string) {
  return request<SesionUsuario>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export async function cerrarSesion() {
  return request<{ revocado: boolean }>("/api/v1/auth/logout", { method: "POST" });
}

export async function quienSoy() {
  return request<{ username: string; plan: string; rol?: string; device_id: string; activo_hasta?: string | null }>("/api/v1/auth/me");
}

export interface RespuestaActivarCodigo {
  activado: boolean;
  plan: string;
  rol: string;
  dias: number;
  activo_hasta: string;
  mensaje: string;
  token: string;
}

export async function activarCodigoWeb(codigo: string) {
  return request<RespuestaActivarCodigo>("/api/v1/auth/activar-codigo", {
    method: "POST",
    body: JSON.stringify({ codigo }),
  });
}
