"""backend/scripts/verificar_datos_reales.py — smoke test con datos REALES (sin mocks).

Pide partidos reales del día al backend real corriendo en localhost:8000, y para una muestra
real evalúa: cobertura de ligas (cuántos partidos reales caen en ligas conocidas vs no),
riqueza de datos del análisis (¿vinieron odds/H2H/standings reales o degradó a default?),
determinismo (¿la misma predicción da el mismo resultado si se pide dos veces?), y el simulador
de liga con una liga real.

Requiere el backend corriendo (`uvicorn backend.api.main:app`) — no es un test de pytest con
mocks, es una verificación empírica end-to-end, exactamente para no depender de lo que la
documentación DICE que pasa. Uso:

    .venv_backend/Scripts/python.exe backend/scripts/verificar_datos_reales.py

Guarda el reporte completo en backend/scripts/_reporte_datos_reales.json (gitignored) y lo
imprime resumido en consola.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.services.ligas import LIGAS, es_liga_conocida  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"
TIMEOUT = 30.0


def fetch_partidos(fecha: str) -> dict:
    r = httpx.get(f"{BASE_URL}/api/v1/partidos", params={"fecha": fecha}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def analizar_cobertura_ligas(stages: list[dict]) -> dict:
    conocidas: list[str] = []
    desconocidas: list[tuple[str, int]] = []
    total_partidos_conocidos = 0
    total_partidos_desconocidos = 0
    posibles_falsos_positivos: list[str] = []

    for s in stages:
        nombre = s.get("Snm", "")
        n_eventos = len(s.get("Events", []))
        if es_liga_conocida(nombre):
            conocidas.append(nombre)
            total_partidos_conocidos += n_eventos
            # Heurística simple: si el nombre real tiene más palabras que la clave que matcheó,
            # podría ser un falso positivo (misma clave, competición distinta) — no concluyente,
            # pero señala candidatos reales a revisar a mano.
            nombre_lower = nombre.lower()
            claves_match = [k for k in LIGAS if k in nombre_lower]
            clave_mas_larga = max(claves_match, key=len) if claves_match else None
            if clave_mas_larga and len(nombre_lower) - len(clave_mas_larga) > 3:
                posibles_falsos_positivos.append(f"{nombre} (matcheó por '{clave_mas_larga}')")
        else:
            desconocidas.append((nombre, n_eventos))
            total_partidos_desconocidos += n_eventos

    return {
        "total_ligas": len(stages),
        "ligas_conocidas": len(conocidas),
        "ligas_desconocidas": len(desconocidas),
        "partidos_en_ligas_conocidas": total_partidos_conocidos,
        "partidos_en_ligas_desconocidas": total_partidos_desconocidos,
        "pct_partidos_con_liga_conocida": round(
            100 * total_partidos_conocidos / max(1, total_partidos_conocidos + total_partidos_desconocidos), 1
        ),
        "ligas_desconocidas_detalle": [{"nombre": n, "partidos": c} for n, c in desconocidas],
        "posibles_falsos_positivos_de_matching": posibles_falsos_positivos,
    }


def elegir_muestra(stages: list[dict], n: int = 5) -> list[dict]:
    """Un partido real por liga conocida, hasta n."""
    muestra = []
    for s in stages:
        if not es_liga_conocida(s.get("Snm", "")):
            continue
        eventos = s.get("Events", [])
        if not eventos:
            continue
        ev = eventos[0]
        t1 = (ev.get("T1") or [{}])[0].get("Nm", "?")
        t2 = (ev.get("T2") or [{}])[0].get("Nm", "?")
        muestra.append({"match_id": ev.get("Eid"), "liga": s.get("Snm"), "local": t1, "visitante": t2})
        if len(muestra) >= n:
            break
    return muestra


def iniciar_sesion(username: str, password: str) -> dict[str, str]:
    """Obtiene un JWT de QA sin registrar ni imprimir secretos."""
    r = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def pedir_prediccion(match_id: str, local: str, visitante: str, liga: str, fecha: str, headers: dict[str, str]) -> dict:
    r = httpx.post(
        f"{BASE_URL}/api/v1/prediccion-web",
        json={"match_id": match_id, "local": local, "visitante": visitante, "liga": liga, "fecha": fecha},
        headers=headers,
        timeout=TIMEOUT,
    )
    return {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text}


def evaluar_riqueza(resultado: dict) -> dict:
    if resultado["status"] != 200:
        return {"ok": False, "status": resultado["status"]}
    b = resultado["body"]
    consenso = b.get("consenso") or {}
    modulos = b.get("modulos") or {}
    pick = str(consenso.get("pick_final") or consenso.get("pick") or "")
    def disponible(texto: object) -> bool:
        valor = str(texto or "").lower()
        return bool(valor) and not any(marca in valor for marca in ("sin datos", "sin historial", "no disponible"))
    return {
        "ok": True,
        "tiene_pick": bool(pick) and "sin pron" not in pick.lower(),
        "odds_disponibles": disponible(b.get("odds_info")),
        "h2h_disponible": disponible(b.get("h2h_resumen")),
        "standings_info": b.get("standings_info"),
        "modulos_disponibles": sorted(modulos),
        "modulos_skip": b.get("modulos_skip") or [],
    }


def probar_determinismo(match_id: str, local: str, visitante: str, liga: str, fecha: str, headers: dict[str, str]) -> dict:
    r1 = pedir_prediccion(match_id, local, visitante, liga, fecha, headers)
    r2 = pedir_prediccion(match_id, local, visitante, liga, fecha, headers)
    if r1["status"] != 200 or r2["status"] != 200:
        return {"comparable": False, "motivo": f"status {r1['status']}/{r2['status']}"}
    p1 = r1["body"].get("consenso", {})
    p2 = r2["body"].get("consenso", {})
    mismo_pick = p1.get("pick_final", p1.get("pick")) == p2.get("pick_final", p2.get("pick"))
    mismas_probs = (
        p1.get("prob_ponderada") == p2.get("prob_ponderada")
    )
    return {
        "comparable": True,
        "mismo_pick_ambas_veces": mismo_pick,
        "mismas_probabilidades_ambas_veces": mismas_probs,
        "pick_1": p1.get("pick_final", p1.get("pick")),
        "pick_2": p2.get("pick_final", p2.get("pick")),
    }


def probar_simulador(liga_slug: str) -> dict:
    r = httpx.get(f"{BASE_URL}/api/v1/simulador/{liga_slug}", timeout=TIMEOUT)
    return {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:500]}


def main() -> None:
    global BASE_URL
    parser = argparse.ArgumentParser(description="Auditoría real de fixtures y predicciones autenticadas.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--username", required=True, help="Usuario de QA existente; no se registra ni se imprime.")
    parser.add_argument("--password", required=True, help="Contraseña del usuario de QA.")
    parser.add_argument("--fecha", default=None, help="Fecha yyyyMMdd; por defecto hoy.")
    parser.add_argument("--muestra", type=int, default=5, help="Máximo de partidos a analizar.")
    args = parser.parse_args()
    BASE_URL = args.base_url.rstrip("/")
    hoy = datetime.now().strftime("%Y%m%d")
    hoy = args.fecha or hoy
    headers = iniciar_sesion(args.username, args.password)

    print(f"=== Pidiendo partidos reales — hoy ({hoy}) ===")
    data_hoy = fetch_partidos(hoy)
    stages = data_hoy.get("Stages", [])
    print(f"fuente={data_hoy.get('fuente')} total={data_hoy.get('total')} ligas={len(stages)}")

    cobertura = analizar_cobertura_ligas(stages)
    print("\n=== Cobertura de ligas (datos reales de hoy) ===")
    print(json.dumps(cobertura, ensure_ascii=False, indent=2)[:2000])

    muestra = elegir_muestra(stages, n=args.muestra)
    print(f"\n=== Muestra de {len(muestra)} partidos reales en ligas conocidas ===")
    predicciones = []
    for m in muestra:
        print(f"  pidiendo análisis real: {m['local']} vs {m['visitante']} ({m['liga']})...")
        res = pedir_prediccion(m["match_id"], m["local"], m["visitante"], m["liga"], hoy, headers)
        riqueza = evaluar_riqueza(res)
        predicciones.append({**m, "riqueza": riqueza})
        print(f"    -> {riqueza}")

    determinismo = None
    if muestra:
        m0 = muestra[0]
        print(f"\n=== Determinismo: pidiendo el mismo análisis 2 veces ({m0['local']} vs {m0['visitante']}) ===")
        determinismo = probar_determinismo(m0["match_id"], m0["local"], m0["visitante"], m0["liga"], hoy, headers)
        print(json.dumps(determinismo, ensure_ascii=False, indent=2))

    print("\n=== Simulador — Premier League y Liga Profesional Argentina ===")
    sim_resultados = {}
    # "premier" (no "premier_league") — slug real definido en top_picks.LIGA_SLUG_POR_ID,
    # confirmado empíricamente 2026-09-09 tras encontrar `{"ok": False, "razon": "liga_slug
    # desconocido: premier_league"}` con el slug incorrecto que tenía este script.
    for slug in ("premier", "liga_profesional"):
        sim_resultados[slug] = probar_simulador(slug)
        print(f"  {slug}: status={sim_resultados[slug]['status']}")

    reporte = {
        "generado_en": datetime.now().isoformat(),
        "fecha_consultada": hoy,
        "cobertura_ligas": cobertura,
        "muestra_predicciones": predicciones,
        "determinismo": determinismo,
        "simulador": sim_resultados,
    }
    out_path = Path(__file__).parent / "_reporte_datos_reales.json"
    out_path.write_text(json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReporte completo guardado en {out_path}")


if __name__ == "__main__":
    main()
