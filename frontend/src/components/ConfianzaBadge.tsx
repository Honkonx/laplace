import { CONFIANZA_DEFINICION, type NivelConfianza } from "@/lib/prediccion";

const ESTILOS: Record<NivelConfianza, { clase: string; etiqueta: string }> = {
  ALTA: { clase: "text-conf-alta", etiqueta: "Confianza alta" },
  MEDIA: { clase: "text-conf-media", etiqueta: "Confianza media" },
  BAJA: { clase: "text-conf-baja", etiqueta: "Confianza baja" },
};

/** Etiqueta con la definición exacta de la banda al pasar el cursor o enfocar. */
export function ConfianzaBadge({ nivel }: { nivel: string }) {
  const clave: NivelConfianza = nivel === "ALTA" || nivel === "MEDIA" ? nivel : "BAJA";
  const estilo = ESTILOS[clave];
  return (
    <span className={`chip font-medium ${estilo.clase}`} title={CONFIANZA_DEFINICION[clave]}>
      {estilo.etiqueta}
    </span>
  );
}
