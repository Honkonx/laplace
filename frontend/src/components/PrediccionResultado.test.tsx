import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ResultadoPrediccion } from "@/lib/api";
import { PrediccionResultado } from "./PrediccionResultado";

function base(consenso: Partial<ResultadoPrediccion["consenso"]>, extra: Partial<ResultadoPrediccion> = {}): ResultadoPrediccion {
  return {
    partido_id: "1", local: "River", visitante: "Boca", liga: "Liga Profesional",
    modulos: {}, modulos_skip: {},
    consenso: { pick_final: "Local", nivel: "MODERADO", score_consenso: 62, confianza_final: "ALTA", detalle: "", total_modulos: 2, coinciden: 2, ...consenso },
    ...extra,
  };
}

describe("PrediccionResultado", () => {
  it("muestra probabilidades del consenso, pick con nombre de equipo, definición de confianza y leyenda honesta", () => {
    render(
      <PrediccionResultado local="River" visitante="Boca" resultado={base({
        prob_ponderada: { local: 0.62, empate: 0.24, visitante: 0.14 },
        peso_efectivo: { odds: 0.7, historico: 0.3 }, modulos_en_consenso: ["odds", "historico"],
      })} />,
    );
    expect(screen.getByText("62%")).toBeInTheDocument();
    expect(screen.getByText("River gana")).toBeInTheDocument();
    expect(screen.getByText(/Probabilidad ponderada del pick de 60% o más/)).toBeInTheDocument();
    expect(screen.getByText(/Cuotas del mercado/)).toBeInTheDocument();
    expect(screen.getByText("70% del peso")).toBeInTheDocument();
    expect(screen.getByText(/no una certeza/)).toBeInTheDocument();
  });

  it("trata «Sin pronóstico» como resultado válido, no como error", () => {
    render(
      <PrediccionResultado local="River" visitante="Boca" resultado={base({
        pick_final: "Sin pronóstico", confianza_final: "SIN DATOS", total_modulos: 0, detalle: "Ningún módulo devolvió resultado válido",
      })} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Sin pronóstico");
    expect(screen.getByText(/Ningún módulo devolvió resultado válido/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/Pick:/)).toBeNull();
  });

  it("avisa cuando el modelo histórico está desactualizado y muestra la tasa base si llega", () => {
    render(
      <PrediccionResultado local="River" visitante="Boca" resultado={base(
        { prob_ponderada: { local: 0.5, empate: 0.3, visitante: 0.2 }, confianza_final: "MEDIA" },
        {
          modulos: { historico: { ok: true, pick: "Local", prob_local: 0.5, prob_empate: 0.3, prob_visitante: 0.2, confianza_score: 50, confianza: "MEDIA", modelo_desactualizado: true, edad_modelo_dias: 600 } },
          tasa_base_liga: { pct_local: 42.7, pct_empate: 32.5, pct_visitante: 24.8, partidos: 1673 },
        },
      )} />,
    );
    expect(screen.getByRole("note")).toHaveTextContent("Modelo desactualizado");
    expect(screen.getByText(/Tasa base de la liga/)).toBeInTheDocument();
    expect(screen.getByText("43%")).toBeInTheDocument();
  });

  it("muestra probabilidades 1X2 individuales por módulo en el desglose", () => {
    render(
      <PrediccionResultado local="River" visitante="Boca" resultado={base(
        {
          prob_ponderada: { local: 0.58, empate: 0.25, visitante: 0.17 },
          peso_efectivo: { odds: 0.7, historico: 0.3 },
          modulos_en_consenso: ["odds", "historico"],
        },
        {
          modulos: {
            odds: { ok: true, pick: "Local", prob_local: 0.6, prob_empate: 0.25, prob_visitante: 0.15, confianza_score: 65, confianza: "ALTA" },
            historico: { ok: true, pick: "Local", prob_local: 0.52, prob_empate: 0.26, prob_visitante: 0.22, confianza_score: 52, confianza: "MEDIA" },
          },
        },
      )} />,
    );
    expect(screen.getByText(/1X2 módulo: L 60\.0% · E 25\.0% · V 15\.0%/)).toBeInTheDocument();
    expect(screen.getByText(/1X2 módulo: L 52\.0% · E 26\.0% · V 22\.0%/)).toBeInTheDocument();
  });
});

describe("PrediccionResultado sin pronóstico explicado", () => {
  it("muestra los motivos y la referencia de la liga como referencia, no como pick", () => {
    render(
      <PrediccionResultado
        local="A"
        visitante="B"
        resultado={{
          partido_id: "1", local: "A", visitante: "B", liga: "L", modulos: {}, modulos_skip: {},
          consenso: { pick_final: "Sin pronóstico", confianza_final: "SIN DATOS", total_modulos: 0, detalle: "x" },
          motivos_sin_pronostico: ["no hay cuotas reales de este partido", "la liga no está en el histórico del bot"],
          referencia_tasa_base: { nivel: "general", pct_local: 44.1, pct_empate: 26.3, pct_visitante: 29.6 },
        } as never}
      />,
    );
    expect(screen.getByText(/no hay cuotas reales de este partido/)).toBeInTheDocument();
    expect(screen.getByText(/Referencia, no pronóstico/)).toBeInTheDocument();
    expect(screen.getByText(/No distingue a estos dos equipos/)).toBeInTheDocument();
  });
});
