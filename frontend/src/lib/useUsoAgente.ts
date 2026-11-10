import { useCallback, useEffect, useState } from "react";
import { obtenerUsoAgente, type UsoAgente } from "./api";

/**
 * Cupo de IA restante. El endpoint /agent/usage lo agrega el backend en paralelo: si aún no
 * existe (404) o falla, `disponible` queda en false y la interfaz degrada sin mostrar un cupo inventado.
 */
export function useUsoAgente(activo: boolean) {
  const [uso, setUso] = useState<UsoAgente | null>(null);
  const [disponible, setDisponible] = useState(false);

  const recargar = useCallback(() => {
    if (!activo) return;
    obtenerUsoAgente()
      .then((u) => { setUso(u); setDisponible(true); })
      .catch(() => { setUso(null); setDisponible(false); });
  }, [activo]);

  useEffect(recargar, [recargar]);
  return { uso, disponible, recargar };
}
