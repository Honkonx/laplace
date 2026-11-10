import { useState } from "react";

interface Props {
  src?: string | null;
  nombre: string;
  /** Clases de tamaño, p. ej. "h-7 w-7" */
  tamano?: string;
}

/** Escudo o logo; si falta o no carga, muestra la inicial en vez de una imagen rota. */
export function Escudo({ src, nombre, tamano = "h-7 w-7" }: Props) {
  const [fallo, setFallo] = useState(false);
  if (src && !fallo) {
    return <img src={src} alt="" className={`${tamano} shrink-0 object-contain`} loading="lazy" onError={() => setFallo(true)} />;
  }
  return (
    <span aria-hidden="true" className={`${tamano} grid shrink-0 place-items-center rounded-md bg-surface-light text-xs font-medium text-text-muted`}>
      {nombre.slice(0, 1)}
    </span>
  );
}
