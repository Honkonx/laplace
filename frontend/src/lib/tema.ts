export type PreferenciaTema = "auto" | "claro" | "oscuro";
const CLAVE = "laplace_web_tema";

export function leerTema(): PreferenciaTema {
  try {
    const v = localStorage.getItem(CLAVE);
    return v === "claro" || v === "oscuro" ? v : "auto";
  } catch {
    return "auto";
  }
}

export function aplicarTema(pref: PreferenciaTema): void {
  const raiz = document.documentElement;
  if (pref === "auto") raiz.removeAttribute("data-theme");
  else raiz.setAttribute("data-theme", pref === "claro" ? "light" : "dark");
  try {
    if (pref === "auto") localStorage.removeItem(CLAVE);
    else localStorage.setItem(CLAVE, pref);
  } catch {
    // sin almacenamiento (modo privado): el tema vale solo para esta visita
  }
}
