"""backend/scripts/diagnostico_cobertura_vivo.py — ¿qué responde HOY el bot a los partidos reales de una fecha?

Usa las APIs reales (consume cuota: pocas peticiones, el día de api-football se pide una vez) y una COPIA de la BD en
`.qa/diag/diag.db`: la BD real nunca se escribe. Para una fecha mide la cobertura del módulo `historico` y de la tabla
`LIGAS` sobre todo el calendario y, para una muestra, pasa cada partido por el pipeline completo
(`_enriquecer_partido` → puerta de calidad → motor → consenso) e imprime fuentes, módulos omitidos, consenso y el mensaje
de "sin pronóstico" si lo hay.

Uso:  .venv_backend\\Scripts\\python.exe backend/scripts/diagnostico_cobertura_vivo.py 20261020 [n_muestra]
"""
import asyncio
import collections
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
copia = REPO / ".qa" / "diag" / "diag.db"
copia.parent.mkdir(parents=True, exist_ok=True)
if not copia.exists():
    shutil.copyfile(REPO / "backend" / "db" / "bot_deportivo.db", copia)
os.environ["DATABASE_URL"] = f"sqlite:///{copia.as_posix()}"
sys.path.insert(0, str(REPO))

import httpx  # noqa: E402

from backend.api.db.session import SessionLocal  # noqa: E402
from backend.api.services import analisis_completo, gateway, ligas, modelo_historico  # noqa: E402

FECHA = sys.argv[1] if len(sys.argv) > 1 else "20261020"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 10


def aplanar(stages):
    for st in stages:
        liga = st.get("Snm") or st.get("CompN") or ""
        pais = st.get("Cnm") or ""
        for ev in st.get("Events", []):
            yield {
                "liga": liga, "pais": pais, "id": str(ev.get("Eid")), "estado": ev.get("Eps"),
                "local": (ev.get("T1") or [{}])[0].get("Nm", ""), "visitante": (ev.get("T2") or [{}])[0].get("Nm", ""),
            }


def _cubre(p: dict) -> bool:
    return modelo_historico.validar_historico({k: p[k] for k in ("liga", "pais", "local", "visitante")})[0]


async def main():
    async with httpx.AsyncClient() as client:
        with SessionLocal() as db:
            stages, fuente = await gateway.obtener_fixtures_cascada(db, client, FECHA)
            partidos = [p for p in aplanar(stages) if p["estado"] in ("NS", None, "")]
            print(f"Fecha {FECHA}: fuente={fuente}, {len(partidos)} partidos programados")
            cubiertos = [p for p in partidos if _cubre(p)]
            conocidas = [p for p in partidos if ligas.es_liga_conocida(p["liga"])]
            pct = lambda n: f"{100 * n / max(1, len(partidos)):.1f}%"  # noqa: E731
            print(f"  con modelo histórico (liga + equipos o un equipo nuevo): {len(cubiertos)} ({pct(len(cubiertos))})")
            print(f"  en la tabla LIGAS: {len(conocidas)} ({pct(len(conocidas))})")
            print("  ligas cubiertas:", dict(collections.Counter((p["pais"], p["liga"]) for p in cubiertos).most_common(10)))

            muestra = cubiertos[: max(0, N - 3)] + [p for p in conocidas if p not in cubiertos][:2]
            muestra += [p for p in partidos if p not in cubiertos and p not in conocidas][:1]
            for p in muestra:
                partido = {"local": p["local"], "visitante": p["visitante"], "liga": p["liga"], "pais": p["pais"]}
                try:
                    enr = await analisis_completo._enriquecer_partido(db, client, partido, p["id"], FECHA)
                    res = await analisis_completo.analizar_y_persistir(
                        db, client, match_id=p["id"], local=p["local"], visitante=p["visitante"], liga=p["liga"],
                        fecha=FECHA, con_ia=False, usuario_id="diag", datos_enriquecidos=enr)
                except Exception as e:  # noqa: BLE001
                    print(f"- {p['local']} vs {p['visitante']} [{p['liga']}]: EXCEPCIÓN {type(e).__name__}: {str(e)[:160]}")
                    continue
                m = res["resultado_motor"]
                cons = m["consenso"]
                cal = res.get("calidad_datos") or {}
                print(f"- {p['local']} vs {p['visitante']} [{p['pais']}/{p['liga']}]")
                print(f"    fuentes={cal.get('sources')} tier={cal.get('tier')} módulos_ok={list(m['modulos'])}")
                print(f"    consenso: pick={cons.get('pick_final')} conf={cons.get('confianza_final')} nivel={cons.get('nivel')} prob={cons.get('prob_ponderada')}")
                if m.get("motivos_sin_pronostico"):
                    print(f"    SIN PRONÓSTICO → {m['motivos_sin_pronostico']} | referencia={ {k: m['referencia_tasa_base'].get(k) for k in ('nivel', 'liga_codigo', 'pct_local', 'pct_empate', 'pct_visitante')} }")


asyncio.run(main())
