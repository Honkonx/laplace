import { useState } from "react";
import { aplicarTema, leerTema, type PreferenciaTema } from "@/lib/tema";

const ORDEN: PreferenciaTema[] = ["auto", "claro", "oscuro"];
const ETIQUETA: Record<PreferenciaTema, string> = { auto: "Auto", claro: "Claro", oscuro: "Oscuro" };

/** Selector manual de tema; "Auto" sigue la preferencia del sistema. */
export function ThemeToggle() {
  const [pref, setPref] = useState<PreferenciaTema>(leerTema);
  function siguiente() {
    const nuevo = ORDEN[(ORDEN.indexOf(pref) + 1) % ORDEN.length];
    aplicarTema(nuevo);
    setPref(nuevo);
  }
  return (
    <button type="button" onClick={siguiente} className="btn btn-ghost btn-sm" aria-label={`Tema: ${ETIQUETA[pref]}. Cambiar tema`} title="Cambiar tema">
      Tema · {ETIQUETA[pref]}
    </button>
  );
}
