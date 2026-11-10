"""backfill_resultados_laboratorio.py — Copia a `resultados_partidos` los partidos terminados de
`partidos_dia` que faltan, y califica con ellos lo que estaba pendiente (comparativos, módulos,
predicciones y experimentos del laboratorio), SIN fuga del futuro.

Motivo (auditoría 2026-10-06, BD real): 693 partidos terminados en `partidos_dia` pero solo 14
en `resultados_partidos` y 16 análisis con resultado — el ledger de verificación estaba casi vacío.

Uso (reglas de `.claude/rules/database-safety.md`):

    python backend/scripts/backfill_resultados_laboratorio.py                    # --dry-run (defecto)
    python backend/scripts/backfill_resultados_laboratorio.py --aplicar --confirmo

- Dry-run por defecto: abre la BD en SOLO LECTURA y reporta cuántas filas añadiría y cuántas
  calificaciones pendientes resolvería. `--aplicar` exige además `--confirmo`.
- Nunca borra. Idempotente: un partido que ya está en `resultados_partidos` no se vuelve a copiar
  (`fixture_id` es único) y `evaluar_partido` solo toca experimentos con `resultado_real` NULL.
- Solo copia datos reales de `partidos_dia` (estado FT/finished con ambos marcadores presentes y
  fecha válida YYYY-MM-DD); excluye AWD/PEN/aplazados/cancelados/en juego — no inventa nada.
- Sin fuga: un análisis creado en o después del inicio del partido NO se califica (quedaría
  sesgado hacia el resultado ya conocido). Para esos partidos solo se copia el resultado oficial al
  ledger y se deja `analisis_comparativo.resultado_real` en NULL. El inicio se toma de
  `partidos_dia.kick_off_utc` y, si falta, se estima con `fecha` + `hora_chile` (Chile). Si no hay
  ninguna de las dos, el análisis NO es verificable y también se deja sin calificar.
- Efecto lateral heredado de `services/resultados._guardar_resultado` (mismo camino que el
  pipeline en vivo): la fila de `partidos_dia` pasa a `status='finished'` y `cache_invalidado=1`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from backend.api.models.partidos import PartidoDia, ResultadoPartido  # noqa: E402
from backend.api.models.predicciones import AnalisisComparativo, PronosticoExperimental  # noqa: E402
from backend.api.services import laboratorio_pronosticos, resultados  # noqa: E402
from backend.api.services.fechas_bd import es_fecha_bd_valida  # noqa: E402

RUTA_BD_DEFECTO = ROOT / "backend" / "db" / "bot_deportivo.db"
TZ_CHILE = ZoneInfo("America/Santiago")
ESTADOS_TERMINADOS = ("FT", "finished")
# Antes de esta fecha `creado_en` se guardaba en hora local de Chile; desde entonces en UTC
# (ver `db/analisis_repo.py::_now_str`).
INICIO_NORMALIZACION_UTC = "2026-09-09"


def _a_utc(texto: str | None, *, tz_naive: timezone | ZoneInfo = timezone.utc) -> datetime | None:
    if not texto:
        return None
    limpio = texto.strip().replace("Z", "").replace("T", " ")[:19]
    try:
        naive = datetime.strptime(limpio, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=tz_naive).astimezone(timezone.utc)


def kickoff_utc(partido: PartidoDia) -> datetime | None:
    """Inicio del partido en UTC: `kick_off_utc` real, o `fecha` + `hora_chile` como estimación."""
    real = _a_utc(partido.kick_off_utc)
    if real is not None:
        return real
    if partido.hora_chile and es_fecha_bd_valida(partido.fecha):
        return _a_utc(f"{partido.fecha} {partido.hora_chile[:5]}:00", tz_naive=TZ_CHILE)
    return None


def creado_utc(creado_en: str | None) -> datetime | None:
    zona = TZ_CHILE if (creado_en or "")[:10] < INICIO_NORMALIZACION_UTC else timezone.utc
    return _a_utc(creado_en, tz_naive=zona)


def _candidatos_terminados(db: Session) -> tuple[list[PartidoDia], dict]:
    """Un partido terminado por `match_id` (el ledger tiene `fixture_id` único); si el mismo
    `match_id` aparece en varias fechas gana la fecha válida más reciente."""
    excluidos = {"sin_marcador": 0, "fecha_invalida": 0, "duplicado_de_match_id": 0}
    elegidos: dict[str, PartidoDia] = {}
    filas = db.query(PartidoDia).filter(PartidoDia.status.in_(ESTADOS_TERMINADOS)).order_by(PartidoDia.fecha.desc()).all()
    for fila in filas:
        if fila.goles_local is None or fila.goles_visitante is None:
            excluidos["sin_marcador"] += 1
        elif not es_fecha_bd_valida(fila.fecha) or len(fila.fecha) != 10:
            excluidos["fecha_invalida"] += 1
        elif fila.match_id in elegidos:
            excluidos["duplicado_de_match_id"] += 1
        else:
            elegidos[fila.match_id] = fila
    return list(elegidos.values()), excluidos


def _analisis_con_fuga(db: Session, partido: PartidoDia) -> tuple[int, int]:
    """(con_fuga_o_no_verificables, verificables_limpios) entre los comparativos sin resultado."""
    inicio = kickoff_utc(partido)
    sucios = limpios = 0
    for comparativo in db.query(AnalisisComparativo).filter(
        AnalisisComparativo.partido_id == partido.match_id, AnalisisComparativo.resultado_real.is_(None)
    ).all():
        creado = creado_utc(comparativo.creado_en)
        if inicio is None or creado is None or creado >= inicio:
            sucios += 1
        else:
            limpios += 1
    return sucios, limpios


def planificar(db: Session) -> dict:
    """Solo lectura: qué copiaría y qué calificaría el backfill."""
    candidatos, excluidos = _candidatos_terminados(db)
    ya_en_ledger = {r[0] for r in db.query(ResultadoPartido.fixture_id).all()}
    a_copiar = [p for p in candidatos if p.match_id not in ya_en_ledger]
    detalle_fuga = {p.match_id: _analisis_con_fuga(db, p) for p in a_copiar}
    experimentos_pendientes = (
        db.query(PronosticoExperimental.id)
        .filter(PronosticoExperimental.resultado_real.is_(None), PronosticoExperimental.partido_id.in_([p.match_id for p in a_copiar]))
        .count() if a_copiar else 0
    )
    return {
        "terminados_en_partidos_dia": len(candidatos), "excluidos": excluidos,
        "ya_en_resultados_partidos": len(candidatos) - len(a_copiar),
        "filas_que_anadiria_a_resultados_partidos": len(a_copiar),
        "comparativos_que_calificaria": sum(limpios for sucios, limpios in detalle_fuga.values() if not sucios),
        "comparativos_sin_calificar_por_fuga_o_kickoff_desconocido": sum(sucios for sucios, _ in detalle_fuga.values()),
        "partidos_con_analisis_contaminado": sum(1 for sucios, _ in detalle_fuga.values() if sucios),
        "experimentos_del_laboratorio_pendientes_que_calificaria": experimentos_pendientes,
        "_partidos": a_copiar,
    }


def _copiar_solo_resultado(db: Session, partido: PartidoDia) -> None:
    """Partido con análisis contaminado: se anota el resultado oficial en el ledger, sin tocar los
    comparativos/módulos/predicciones (no se califica lo hecho con el desenlace ya conocido)."""
    goles_l, goles_v = int(partido.goles_local), int(partido.goles_visitante)
    ganador = "local" if goles_l > goles_v else "visitante" if goles_v > goles_l else "empate"
    db.add(ResultadoPartido(
        fixture_id=partido.match_id, local=partido.local, visitante=partido.visitante, liga=partido.liga_nombre,
        goles_local=goles_l, goles_visitante=goles_v, ganador=ganador, status_api=partido.status,
        fecha_partido=partido.fecha, actualizado_en=resultados._now(),
    ))
    laboratorio_pronosticos.evaluar_partido(db, partido_id=partido.match_id, goles_local=goles_l, goles_visitante=goles_v)
    db.commit()


def aplicar(db: Session, plan: dict) -> dict:
    copiados = calificados_normal = solo_ledger = 0
    for partido in plan["_partidos"]:
        sucios, _limpios = _analisis_con_fuga(db, partido)
        if sucios:
            _copiar_solo_resultado(db, partido)
            solo_ledger += 1
        else:
            resultados._guardar_resultado(
                db, partido.match_id, partido.local or "", partido.visitante or "", partido.liga_nombre or "",
                int(partido.goles_local), int(partido.goles_visitante), partido.status or "FT", partido.fecha,
            )
            calificados_normal += 1
        copiados += 1
    reconciliacion = laboratorio_pronosticos.reconciliar_resultados_experimentales(db, limite=100_000)
    db.commit()
    return {
        "copiados_a_resultados_partidos": copiados, "con_calificacion_completa": calificados_normal,
        "solo_resultado_por_fuga": solo_ledger, "reconciliacion_experimentos": reconciliacion,
    }


def _crear_sesion(ruta: Path, escritura: bool) -> Session:
    if not ruta.exists():
        raise SystemExit(f"No existe la BD: {ruta}")
    uri = f"sqlite:///file:{ruta.as_posix()}?mode={'rw' if escritura else 'ro'}&uri=true"
    return sessionmaker(bind=create_engine(uri))()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=RUTA_BD_DEFECTO, help="ruta de la BD SQLite")
    parser.add_argument("--aplicar", action="store_true", help="escribe los cambios (exige --confirmo)")
    parser.add_argument("--confirmo", action="store_true", help="confirmación explícita para --aplicar")
    args = parser.parse_args(argv)
    if args.aplicar and not args.confirmo:
        print("ABORTADO: --aplicar exige --confirmo (escribe en resultados_partidos y califica análisis).", file=sys.stderr)
        return 2

    db = _crear_sesion(args.db, escritura=args.aplicar)
    try:
        plan = planificar(db)
        reporte = {"modo": "aplicar" if args.aplicar else "dry-run", "bd": str(args.db),
                   **{k: v for k, v in plan.items() if not k.startswith("_")}}
        if args.aplicar:
            reporte["resultado"] = aplicar(db, plan)
        print(json.dumps(reporte, ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
