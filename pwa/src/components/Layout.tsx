import { Outlet } from "react-router-dom";
import { BottomNav } from "./BottomNav";

// Shell de la PWA: sin header de escritorio (sin menú horizontal, sin logo+links arriba como
// frontend/src/components/Layout.tsx) — navegación tipo app, todo vive en la bottom nav fija.
// `pb-24` deja espacio para que el contenido no quede tapado por la nav; el padding-top inline
// respeta el notch/status bar (safe-area-inset-top) cuando corre standalone (instalada) en
// iOS/Android.
export function Layout() {
  return (
    <div className="min-h-dvh bg-bg text-text">
      <main
        className="mx-auto max-w-md px-4 pb-24"
        style={{ paddingTop: "max(20px, env(safe-area-inset-top))" }}
      >
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}
