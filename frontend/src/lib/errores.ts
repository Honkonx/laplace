import { ApiError } from "./api";

export type TipoError = "limite" | "permiso" | "sesion" | "red" | "servidor" | "otro";

export interface ErrorAmigable {
  tipo: TipoError;
  titulo: string;
  detalle: string;
  /** Segundos hasta que tiene sentido reintentar (solo límites) */
  esperaSeg?: number;
  reintentable: boolean;
}

/** Traduce cualquier excepción a un mensaje que diga qué pasó y qué hacer. */
export function describirError(e: unknown): ErrorAmigable {
  if (e instanceof ApiError) {
    if (e.status === 429) {
      const diario = /hoy|diari/i.test(e.message);
      const esperaSeg = e.retryAfter ?? (diario ? undefined : 60);
      return {
        tipo: "limite",
        titulo: diario ? "Llegaste al límite de hoy" : "Demasiadas consultas seguidas",
        detalle: diario
          ? "El cupo diario de IA se agotó. Puedes seguir con respuestas por reglas, sin IA, o volver mañana."
          : "Espera un momento antes de volver a preguntar.",
        esperaSeg,
        reintentable: !diario,
      };
    }
    if (e.status === 401) return { tipo: "sesion", titulo: "Tu sesión venció", detalle: "Vuelve a entrar para seguir.", reintentable: false };
    if (e.status === 403) return { tipo: "permiso", titulo: "No tienes permiso para esto", detalle: e.message, reintentable: false };
    if (e.status >= 500) return { tipo: "servidor", titulo: "El servidor tuvo un problema", detalle: "Prueba de nuevo en unos segundos.", reintentable: true };
    return { tipo: "otro", titulo: "No se pudo completar", detalle: e.message, reintentable: true };
  }
  if (e instanceof TypeError) {
    return { tipo: "red", titulo: "Sin conexión con Laplace", detalle: "Revisa tu conexión o que el servicio esté encendido, y reintenta.", reintentable: true };
  }
  return { tipo: "otro", titulo: "Algo salió mal", detalle: e instanceof Error ? e.message : "Error desconocido.", reintentable: true };
}
