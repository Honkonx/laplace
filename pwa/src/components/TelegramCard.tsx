import { canalTelegram, urlCanalTelegram } from "@/lib/comunidad";

// Tarjeta de comunidad de Telegram — espeja el ".tg-card" del mockup A1. El canal sale de VITE_TELEGRAM_CANAL
// (ver lib/comunidad.ts); si no está configurado, la tarjeta no se muestra.
export function TelegramCard() {
  const canal = canalTelegram();
  if (!canal) return null;
  return (
    <a
      href={urlCanalTelegram()}
      target="_blank"
      rel="noreferrer"
      className="flex flex-none items-center gap-3 rounded-2xl px-4 py-3"
      style={{ background: "linear-gradient(135deg,#2AABEE,#229ED9)" }}
    >
      <div className="flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-white/15 text-lg">
        ✈
      </div>
      <div className="flex-1 text-white">
        <p className="text-sm font-bold">Comunidad Laplace</p>
        <p className="text-xs opacity-85">Canal @{canal} · picks gratis</p>
      </div>
      <span className="flex-none rounded-full bg-white px-3 py-1.5 text-xs font-bold text-[#229ED9]">
        Unirse
      </span>
    </a>
  );
}
