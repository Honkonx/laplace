// Canal de Telegram de la comunidad. No hay ninguno fijo en el código: se configura al compilar con VITE_TELEGRAM_CANAL
// (por ejemplo `VITE_TELEGRAM_CANAL=@mi_canal` en `.env.local`). Sin valor, la PWA no muestra ningún enlace a Telegram.
export function canalTelegram(): string {
  const bruto = String(import.meta.env.VITE_TELEGRAM_CANAL ?? "").trim();
  return bruto.replace(/^@/, "");
}

export function urlCanalTelegram(): string {
  const canal = canalTelegram();
  return canal ? `https://t.me/${canal}` : "";
}
