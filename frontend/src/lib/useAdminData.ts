import { useEffect, useState } from "react";
import { ApiError } from "./api";

// Hook compartido por las 6 secciones de /admin — todas siguen el mismo patrón
// fetch-al-cargar/loading/error (DRY, ver .claude/rules/clean-code-principles.md).
export function useAdminData<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [datos, setDatos] = useState<T | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    setCargando(true);
    setError(null);
    fetcher()
      .then((r) => {
        if (!cancelado) setDatos(r);
      })
      .catch((e) => {
        if (!cancelado) {
          setError(e instanceof ApiError ? e.message : "No se pudo cargar la información.");
        }
      })
      .finally(() => {
        if (!cancelado) setCargando(false);
      });
    return () => {
      cancelado = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { datos, cargando, error };
}
