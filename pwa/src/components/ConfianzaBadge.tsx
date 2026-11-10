const ESTILOS: Record<string, { color: string; label: string }> = {
  ALTA: { color: "var(--color-conf-alta)", label: "Confianza alta" },
  MEDIA: { color: "var(--color-conf-media)", label: "Confianza media" },
  BAJA: { color: "var(--color-conf-baja)", label: "Confianza baja" },
};

export function ConfianzaBadge({ nivel, score }: { nivel: string; score?: number }) {
  const estilo = ESTILOS[nivel] ?? ESTILOS.BAJA;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-xs font-medium">
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: estilo.color }} aria-hidden />
      <span style={{ color: estilo.color }}>{estilo.label}</span>
      {score !== undefined && <span className="font-mono text-text-dim">{score}/100</span>}
    </span>
  );
}
