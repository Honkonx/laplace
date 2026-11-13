import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "@/lib/AuthContext";
import { Layout } from "@/components/Layout";
import { Home } from "@/pages/Home";
import { Entrar } from "@/pages/Entrar";
import { Simulador } from "@/pages/Simulador";
import { Admin } from "@/pages/Admin";
import { Agente } from "@/pages/Agente";
import { Historial } from "@/pages/Historial";
import { Seguimientos } from "@/pages/Seguimientos";
import { EstadoBot } from "@/pages/EstadoBot";
import { NoEncontrada } from "@/pages/NoEncontrada";

export function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="entrar" element={<Entrar />} />
            <Route path="simulador" element={<Simulador />} />
            <Route path="admin" element={<Admin />} />
            <Route path="agente" element={<Agente />} />
            <Route path="historial" element={<Historial />} />
            <Route path="seguimientos" element={<Seguimientos />} />
            <Route path="estado" element={<EstadoBot />} />
            <Route path="*" element={<NoEncontrada />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
