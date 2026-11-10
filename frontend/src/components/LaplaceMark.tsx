/** Marca de Laplace: una curva de probabilidad con tres puntos (local, empate, visitante). Hereda el color del texto. */
export function LaplaceMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" className={className} aria-hidden="true">
      <rect x="1.5" y="1.5" width="29" height="29" rx="7" stroke="currentColor" strokeWidth="1.8" />
      <path d="M7 22c3-1 4-12 9-12s6 11 9 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="16" cy="10" r="2" fill="var(--t-accent)" />
    </svg>
  );
}
