"""backend/scripts/exportar_resultados_vivos.py — capa de resultados en vivo para reajustar los modelos.

Lee (SOLO lectura, `mode=ro`) `resultados_partidos` y los terminados de `partidos_dia` de la BD del
bot, traduce cada marcador real al esquema canónico del maestro (liga del histórico y nombres de
equipo del artefacto Dixon-Coles) y escribe `backend/data/datos/vivo/resultados_vivos.csv.gz`
con `fuente='laplace_vivo'`. NO toca el maestro ni la BD.

  - Idempotente: la capa es acumulativa (conserva lo exportado antes, porque el job de purga borra
    `partidos_dia` de más de 90 días) y la escritura es determinista: re-ejecutar con la misma BD
    produce los mismos bytes.
  - Nunca mezcla filas dudosas: si la liga o un equipo no se resuelve con certeza contra el modelo de
    esa liga, la fila se descarta y el reporte dice por qué (`reporte_exportacion.json`).
  - `--dry-run` (por defecto) solo calcula y muestra el reporte; `--aplicar` escribe la capa.

No necesita numpy/scipy (solo librería estándar + `services/modelo_historico` para resolver nombres).
Uso:  python backend/scripts/exportar_resultados_vivos.py [--aplicar] [--db ruta] [--salida ruta]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.api.ml import datos, vivo  # noqa: E402

RUTA_BD = REPO / "backend" / "db" / "bot_deportivo.db"


class SinArtefacto(RuntimeError):
    """No hay modelo entrenado contra el que resolver ligas y equipos. Es una excepción normal (no SystemExit): este módulo también lo importa el
    backend, y un SystemExit que escapa de un trabajo programado puede detener todo el proceso (hallazgo de la auditoría del 2026-11-09)."""


def construir_resolver():
    """Adaptador sobre `services/modelo_historico`: (codigo, local, visitante) o (None, razon, detalle)."""
    from backend.api.services import modelo_historico as mh

    art = mh._artefactos()
    if art is None:
        raise SinArtefacto("Sin artefacto dixon_coles_ligas.json: no hay contra qué resolver ligas y equipos")

    def resolver(c: dict) -> tuple:
        d = {"liga": c["liga"], "liga_id": c["liga_id"], "local": c["local"], "visitante": c["visitante"]}
        candidatas = mh.ligas_candidatas(d)
        if not candidatas:
            return None, "liga_sin_modelo", f"{c['liga']} [{c['liga_id']}]"
        r = mh._resolver(d)
        if r[0]:
            return r[0], r[2], r[3]
        faltan = [n for n in (c["local"], c["visitante"]) if not mh._resolver_equipo(art, candidatas[0], n)]
        return None, "equipo_desconocido", f"{candidatas[0]}: " + " | ".join(faltan)

    return resolver, art, mh


def metadatos_ligas(art: dict, mh, maestro: list[dict]) -> dict[str, dict]:
    """{codigo: {nombre, pais, europea}}: nombre del artefacto, país de la tabla de ligas y si la liga
    etiqueta sus temporadas como 'aaaa/bbbb' (según su última temporada en el maestro)."""
    ultima: dict[str, str] = {}
    for p in maestro:  # ordenado por fecha: la última asignación es la temporada más reciente
        ultima[p["liga"]] = p["temporada"]
    crudo = json.loads((mh.DIR_ARTEFACTOS / "dixon_coles_ligas.json").read_text(encoding="utf-8"))["ligas"]
    paises = art["tabla_ligas"]["paises"]
    return {c: {"nombre": crudo[c].get("nombre", ""), "pais": paises.get(c, ""), "europea": "/" in ultima.get(c, "")}
            for c in art["ligas"]}


def exportar(ruta_bd: Path, salida: Path, aplicar: bool, reporte: Path | None = None, base: Path | None = None) -> dict:
    """`base`: capa previa de la que se parte (por defecto `salida`); permite un ensayo que no toca la real."""
    resolver, art, mh = construir_resolver()
    maestro = datos.cargar_partidos()
    metas = metadatos_ligas(art, mh, maestro)
    existentes = vivo.leer_csv_gz(base if base is not None else salida)
    crudos = vivo.leer_crudos_bd(ruta_bd)
    filas, descartes = vivo.clasificar(crudos, resolver, metas, existentes)
    previos = len(existentes)
    resumen = {
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bd": str(ruta_bd), "salida": str(salida), "aplicado": aplicar,
        "crudos_leidos": len(crudos), "filas_previas": previos, "filas_nuevas": len(filas) - previos,
        **vivo.resumen_por_liga(filas, descartes),
        "descartes": [d for d in descartes if d["razon"] != "duplicado"],
    }
    if aplicar:
        vivo.escribir_csv_gz(filas, salida)
        destino = reporte or salida.with_name("reporte_exportacion.json")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    return resumen


def imprimir(resumen: dict) -> None:
    print(f"crudos leídos: {resumen['crudos_leidos']} | filas en la capa: {resumen['filas_totales']} "
          f"({resumen['filas_nuevas']:+d} frente a lo exportado antes) | duplicados ignorados: {resumen['duplicados_ignorados']}")
    print("asignados por liga:", ", ".join(f"{k}={v}" for k, v in resumen["por_liga"].items()) or "(ninguno)")
    print("descartes por razón:", resumen["descartes_por_razon"])
    faltan: dict[str, int] = {}
    for d in resumen["descartes"]:
        if d["razon"] == "equipo_desconocido":
            faltan[d["detalle"]] = faltan.get(d["detalle"], 0) + 1
    for detalle, n in sorted(faltan.items(), key=lambda kv: -kv[1])[:15]:
        print(f"  equipo sin modelo: {detalle} (x{n})")
    print("ESCRITO" if resumen["aplicado"] else "DRY-RUN: no se escribió nada (usar --aplicar)")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consola Windows cp1252
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", type=Path, default=RUTA_BD)
    ap.add_argument("--salida", type=Path, default=datos.RUTA_VIVO)
    ap.add_argument("--aplicar", action="store_true", help="escribe la capa (por defecto solo dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="explícito; es el comportamiento por defecto")
    ap.add_argument("--json", action="store_true", help="imprime el resumen completo como JSON")
    args = ap.parse_args()
    try:
        resumen = exportar(args.db, args.salida, aplicar=args.aplicar and not args.dry_run)
    except SinArtefacto as exc:
        raise SystemExit(str(exc)) from exc  # en la línea de comandos sí corresponde terminar con el mensaje
    if args.json:
        print(json.dumps(resumen, indent=2, ensure_ascii=False))
    else:
        imprimir(resumen)


if __name__ == "__main__":
    main()
