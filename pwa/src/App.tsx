import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "@/lib/AuthContext";
import { Layout } from "@/components/Layout";
import { Home } from "@/pages/Home";
import { Calendario } from "@/pages/Calendario";
import { TopPicks } from "@/pages/TopPicks";
import { Simulador } from "@/pages/Simulador";
import { Perfil } from "@/pages/Perfil";
import { Entrar } from "@/pages/Entrar";
import { Agente } from "@/pages/Agente";

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="calendario" element={<Calendario />} />
            <Route path="picks" element={<TopPicks />} />
            <Route path="simulador" element={<Simulador />} />
            <Route path="perfil" element={<Perfil />} />
            <Route path="agente" element={<Agente />} />
            <Route path="entrar" element={<Entrar />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
