#!/usr/bin/env python3
"""verificar_calidad_datos_reales.py — Verificación empírica contra el backend REAL corriendo,
con partidos/ligas de HOY (datos reales, no mocks). No es parte de la suite de pytest (necesita
red real, API keys reales, y el servidor levantado) — correr a mano cuando se quiera auditar la
calidad real de los datos, no en CI.

Qué verifica, con datos de hoy:
  1. Cobertura de ligas — de todas las ligas que trae la fuente de fixtures real hoy, ¿cuántas
     conoce `services/ligas.py` (LIGAS)? Lista las que NO conoce (mapeo incompleto real, no
     hipotético).
  2. Consistencia cruzada — para una muestra de partidos reales, compara el pick del motor
     estadístico (Poisson/Dixon-Coles/consenso) entre las DOS superficies reales que lo exponen:
     el webhook de la app (`POST /webhook/kairos-app`, action="prediccion", vía job asíncrono) y
     el endpoint público de la web (`POST /api/v1/prediccion-web`, síncrono, sin IA). Ambas deben
     coincidir en el pick estadístico base — si divergen, es un bug real de consistencia entre
     motores, no un resultado esperado (la única divergencia esperada es la capa de IA, que solo
     corre en el path del webhook para planes pro/max, nunca en prediccion-web).
  3. Riqueza de datos — para la misma muestra, qué fracción de partidos reales trae
     standings/odds/H2H disponibles vs. no disponibles ("sin datos") — cuantifica qué tan
     completa es la información real que entra al análisis, no solo si el pipeline "no truena".

Uso:
    cd <carpeta del proyecto>
    .venv_backend/Scripts/python.exe backend/scripts/verificar_calidad_datos_reales.py [--muestra N]

Requiere: backend real corriendo en BASE_URL (default http://127.0.0.1:8000), con las API keys
reales de .env configuradas (SPORTS_API_KEY, ODDSAPI_KEY, etc. — lo que ya usa el backend real).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

# La consola de Windows no siempre usa UTF-8 (cp1252 por defecto) — sin esto, cualquier print con
# un caracter fuera de ese charset (✓, →, etc.) revienta con UnicodeEncodeError. Encontrado real
# corriendo este script la primera vez. reconfigure() existe desde Python 3.7.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api.core.config import settings  # noqa: E402
from backend.api.services.ligas import LIGAS, es_liga_conocida  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"


def _get(client: httpx.Client, path: str, **kw) -> httpx.Response:
    return client.get(f"{BASE_URL}{path}", timeout=30, **kw)


def _post_webhook(client: httpx.Client, action: str, params: dict, device_id: str = "verificacion-real") -> dict:
    body = {
        "action": action, "params": params, "device_id": device_id,
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    r = client.post(
        f"{BASE_URL}/webhook/kairos-app", json=body,
        headers={"x-kairos-key": settings.KAIROS_AUTH_SECRET}, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _stages_reales(client: httpx.Client, fecha: str) -> list[dict]:
    """Shape REAL confirmada corriendo el endpoint (no la documentación, que en ningún lado
    describe este contrato exacto): `GET /api/v1/partidos` devuelve
    `{"ok", "fuente", "total", "Stages": [{"Snm", "liga_slug", "Events": [{"Eid","Eps","T1",
    "T2","Esd",...}]}]}` — NO `{"ligas": {...}}` ni `{"partidos": [...]}` como se asumió al
    escribir la primera versión de este script. `T1`/`T2` son listas de un elemento con `Nm`
    (nombre del equipo)."""
    resp = _get(client, "/api/v1/partidos", params={"fecha": fecha})
    resp.raise_for_status()
    data = resp.json()
    return data.get("Stages") or []


def verificar_cobertura_ligas(client: httpx.Client, fecha: str) -> list[str]:
    print(f"\n{'=' * 70}\n1. COBERTURA DE LIGAS -- partidos reales de hoy ({fecha})\n{'=' * 70}")
    stages = _stages_reales(client, fecha)
    nombres = sorted({s.get("Snm", "?") for s in stages})

    print(f"Ligas reales encontradas hoy: {len(nombres)}")
    desconocidas = [n for n in nombres if not es_liga_conocida(n)]
    for n in nombres:
        estado = "OK conocida" if es_liga_conocida(n) else "?? DESCONOCIDA (usa DEFAULT_LIGA_AVG)"
        print(f"  - {n}: {estado}")
    print(f"\nResultado: {len(nombres) - len(desconocidas)}/{len(nombres)} ligas reales de hoy "
          f"estan cubiertas por LIGAS ({len(LIGAS)} entradas en la tabla).")
    if desconocidas:
        print(f"Desconocidas hoy (candidatas reales a agregar a services/ligas.py): {desconocidas}")
    return desconocidas


def _muestra_partidos(client: httpx.Client, fecha: str, n: int) -> list[dict]:
    stages = _stages_reales(client, fecha)
    partidos: list[dict] = []
    for s in stages:
        liga = s.get("Snm", "?")
        for ev in s.get("Events", []):
            t1 = (ev.get("T1") or [{}])[0].get("Nm", "?")
            t2 = (ev.get("T2") or [{}])[0].get("Nm", "?")
            partidos.append({
                "id": ev.get("Eid"), "local": t1, "visitante": t2, "liga": liga,
                "status": ev.get("Eps", ""),
            })
    # "NS" (not started) — partidos que todavía no arrancaron, para que el análisis tenga sentido
    candidatos = [p for p in partidos if p["status"] == "NS"]
    return candidatos[:n]


def _headers_web(client: httpx.Client, username: str, password: str) -> dict[str, str]:
    """Inicia sesión de QA para probar el contrato web real sin exponer el JWT."""
    login = client.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    login.raise_for_status()
    return {"Authorization": f"Bearer {login.json()['token']}"}


def verificar_consistencia_y_riqueza(client: httpx.Client, fecha: str, muestra: int, headers_web: dict[str, str]) -> None:
    print(f"\n{'=' * 70}\n2-3. CONSISTENCIA CRUZADA + RIQUEZA DE DATOS — muestra real\n{'=' * 70}")
    print("Nota real (confirmada corriendo el script, no asumida antes de correrlo): el path de "
          "la app (webhook -> check_job) devuelve `content` como un DICT estructurado "
          "({'pick','confianza','score','fuente','texto_completo'}), no el texto plano que se "
          "esperaba al escribir la primera versión de esto. La comparación de abajo usa "
          "content['pick'] directo, no heurística de texto.")
    partidos = _muestra_partidos(client, fecha, muestra)
    if not partidos:
        print("Sin partidos pendientes hoy para muestrear — reintentar en otra fecha/hora real.")
        return

    fecha_guiones = f"{fecha[:4]}-{fecha[4:6]}-{fecha[6:8]}"
    resultados = []
    for p in partidos:
        match_id = str(p.get("id") or p.get("Eid") or "")
        local, visitante, liga = p.get("local", "?"), p.get("visitante", "?"), p.get("liga", "?")
        print(f"\n--- {local} vs {visitante} ({liga}) — match_id={match_id} ---")

        # Path web (público, síncrono, sin IA)
        pick_web, datos_web = None, None
        try:
            r = client.post(f"{BASE_URL}/api/v1/prediccion-web", json={
                "match_id": match_id, "local": local, "visitante": visitante,
                "liga": liga, "fecha": fecha,
            }, headers=headers_web, timeout=45)
            r.raise_for_status()
            web = r.json()
            pick_web = web.get("consenso", {}).get("pick") or web.get("modulos", {}).get("poisson", {}).get("pick")
            datos_web = {
                "standings": web.get("standings_info") not in (None, "", "No disponible"),
                "odds": web.get("odds_info") not in (None, "", "No disponible"),
                "h2h": web.get("h2h_resumen") not in (None, "", "No disponible"),
            }
            print(f"  Web  (prediccion-web, sin IA): pick={pick_web!r} | datos={datos_web}")
        except Exception as e:  # noqa: BLE001 — reporte de verificación, no debe cortar la corrida
            print(f"  Web  (prediccion-web): ERROR real — {e}")

        # Path app (webhook, job asíncrono, puede incluir IA en plan pro/max) — params reales
        # confirmados leyendo app_gateway.py::_accion_prediccion: "date" con guiones, no "fecha".
        content_app = None
        try:
            resp = _post_webhook(client, "prediccion", {"match_id": match_id, "local": local,
                                                          "visitante": visitante, "league": liga,
                                                          "date": fecha_guiones})
            job_id = (resp.get("data") or {}).get("job_id")
            if job_id and job_id != "cache":
                for _ in range(20):
                    time.sleep(1.5)
                    chk = _post_webhook(client, "check_job", {"job_id": job_id})
                    status = (chk.get("data") or {}).get("status")
                    if status == "listo":
                        content_app = (chk.get("data") or {}).get("content")
                        print(f"  App  (webhook, job {job_id}, status=listo): {content_app!r:.200}")
                        break
                    if status == "error":
                        print(f"  App  (webhook, job {job_id}): terminó en error — {chk.get('data')}")
                        break
                else:
                    print(f"  App  (webhook, job {job_id}): no terminó en el tiempo de espera del script")
            else:
                content_app = (resp.get("data") or {}).get("content")
                print(f"  App  (webhook, {'cache' if job_id == 'cache' else 'respuesta directa'}): {content_app!r:.200}")
        except Exception as e:  # noqa: BLE001
            print(f"  App  (webhook): ERROR real — {e}")

        # `content` SÍ es un dict estructurado ({"pick","confianza","score","fuente",
        # "texto_completo"}) — no el string plano que se asumió al escribir la primera versión de
        # este script (confirmado corriéndolo). Comparación directa de campo, no heurística.
        pick_app = content_app.get("pick") if isinstance(content_app, dict) else None
        coincide = (pick_web is not None and pick_app is not None and pick_web == pick_app)

        resultados.append({"partido": f"{local} vs {visitante}", "pick_web": pick_web,
                            "pick_app": pick_app, "coincide": coincide, "datos_web": datos_web})

    print(f"\n{'=' * 70}\nRESUMEN\n{'=' * 70}")
    for r in resultados:
        if r["coincide"] is None:
            estado = "-- no comparable (falló alguno de los dos paths, ver arriba)"
        elif r["coincide"]:
            estado = "OK COINCIDE"
        else:
            estado = "!! DIVERGE (revisar -- ambos deberían usar el mismo motor estadístico)"
        print(f"  {r['partido']}: web={r['pick_web']!r} app={r.get('pick_app')!r} -> {estado}")
    con_datos_completos = sum(1 for r in resultados if r["datos_web"] and all(r["datos_web"].values()))
    print(f"\nPartidos con standings+odds+H2H completos: {con_datos_completos}/{len(resultados)}")


def main() -> None:
    global BASE_URL
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", type=int, default=3, help="Cuántos partidos reales samplear (default 3)")
    ap.add_argument("--fecha", default=None, help="yyyyMMdd — default hoy")
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--username", required=True, help="Usuario de QA existente; no se registra ni se imprime")
    ap.add_argument("--password", required=True, help="Contraseña del usuario de QA")
    args = ap.parse_args()
    BASE_URL = args.base_url.rstrip("/")
    fecha = args.fecha or datetime.now().strftime("%Y%m%d")

    with httpx.Client() as client:
        try:
            _get(client, "/docs")
        except Exception:
            print(f"ERROR: el backend no responde en {BASE_URL} — levantalo primero (uvicorn backend.api.main:app).")
            sys.exit(1)

        headers_web = _headers_web(client, args.username, args.password)
        verificar_cobertura_ligas(client, fecha)
        verificar_consistencia_y_riqueza(client, fecha, args.muestra, headers_web)


if __name__ == "__main__":
    main()
