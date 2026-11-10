import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function cargarTarjeta() {
  vi.resetModules();
  return (await import("./TelegramCard")).TelegramCard;
}

describe("TelegramCard", () => {
  it("sin canal configurado no muestra ninguna tarjeta ni enlace a Telegram", async () => {
    vi.stubEnv("VITE_TELEGRAM_CANAL", "");
    const TelegramCard = await cargarTarjeta();
    const { container } = render(<TelegramCard />);
    expect(container).toBeEmptyDOMElement();
  });

  it("con canal configurado enlaza a ese canal (con o sin @)", async () => {
    vi.stubEnv("VITE_TELEGRAM_CANAL", "@mi_canal");
    const TelegramCard = await cargarTarjeta();
    render(<TelegramCard />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "https://t.me/mi_canal");
    expect(screen.getByText(/@mi_canal/)).toBeInTheDocument();
  });
});
