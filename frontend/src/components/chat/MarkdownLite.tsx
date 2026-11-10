import type { ReactNode } from "react";

// Renderizador mínimo y seguro del texto del agente: párrafos, listas, tablas simples,
// **negrita** y `código`. Todo se construye con elementos de React (nunca innerHTML), así
// que un texto del modelo no puede inyectar marcado.

function inline(texto: string): ReactNode[] {
  return texto.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((trozo, i) => {
    if (trozo.startsWith("**") && trozo.endsWith("**")) return <strong key={i} className="font-semibold">{trozo.slice(2, -2)}</strong>;
    if (trozo.startsWith("`") && trozo.endsWith("`")) return <code key={i} className="num rounded bg-surface-light px-1 py-0.5 text-[0.85em]">{trozo.slice(1, -1)}</code>;
    return trozo;
  });
}

const esViñeta = (l: string) => /^\s*[-*•]\s+/.test(l);
const esNumerada = (l: string) => /^\s*\d+[.)]\s+/.test(l);
const esFilaTabla = (l: string) => l.trim().startsWith("|") && l.trim().endsWith("|");
const esSeparador = (l: string) => /^\s*\|?[\s:-]+(\|[\s:-]+)+\|?\s*$/.test(l);

function celdas(l: string): string[] {
  return l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

function Tabla({ lineas }: { lineas: string[] }) {
  const [cabecera, ...resto] = lineas.filter((l) => !esSeparador(l));
  return (
    <div className="my-2 overflow-x-auto">
      <table className="w-full min-w-max border-collapse text-left text-[13px]">
        <thead>
          <tr>{celdas(cabecera).map((c, i) => <th key={i} className="border-b border-border px-2 py-1.5 font-medium text-text-muted">{inline(c)}</th>)}</tr>
        </thead>
        <tbody>
          {resto.map((fila, i) => (
            <tr key={i}>{celdas(fila).map((c, j) => <td key={j} className="border-b border-border px-2 py-1.5">{inline(c)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Bloque({ lineas }: { lineas: string[] }) {
  if (lineas.length >= 2 && lineas.every(esFilaTabla) && lineas.some(esSeparador)) return <Tabla lineas={lineas} />;
  if (lineas.every(esViñeta)) {
    return <ul className="my-2 list-disc space-y-1 pl-5">{lineas.map((l, i) => <li key={i}>{inline(l.replace(/^\s*[-*•]\s+/, ""))}</li>)}</ul>;
  }
  if (lineas.every(esNumerada)) {
    return <ol className="my-2 list-decimal space-y-1 pl-5">{lineas.map((l, i) => <li key={i}>{inline(l.replace(/^\s*\d+[.)]\s+/, ""))}</li>)}</ol>;
  }
  return (
    <p className="my-2 first:mt-0 last:mb-0">
      {lineas.map((l, i) => <span key={i}>{i > 0 && <br />}{inline(l)}</span>)}
    </p>
  );
}

export function MarkdownLite({ texto }: { texto: string }) {
  const bloques = texto.trim().split(/\n\s*\n/).map((b) => b.split("\n").filter((l) => l.trim() !== ""));
  return <div className="break-words text-[15px] leading-relaxed">{bloques.filter((b) => b.length).map((b, i) => <Bloque key={i} lineas={b} />)}</div>;
}
