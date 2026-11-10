// Banner de portada de Home: degradé con los colores de marca y el logo de Laplace.
interface Props {
  titulo: string;
  subtitulo: string;
}

export function HeroBanner({ titulo, subtitulo }: Props) {
  return (
    <div
      className="relative flex h-28 flex-none flex-col justify-between overflow-hidden rounded-2xl p-4"
      style={{
        background:
          "radial-gradient(120% 90% at 15% 0%, #242853, transparent 60%), radial-gradient(90% 90% at 100% 10%, var(--color-accent-glow), transparent 55%), linear-gradient(160deg, #242853, var(--color-bg))",
      }}
    >
      <img src="/icons/icon-192.png" alt="Laplace" width={44} height={44} className="absolute bottom-3 right-3 h-11 w-11 rounded-xl shadow-lg" />
      <div>
        <p className="font-display text-base font-bold text-white drop-shadow">{titulo}</p>
        <p className="text-xs text-white/80">{subtitulo}</p>
      </div>
    </div>
  );
}
