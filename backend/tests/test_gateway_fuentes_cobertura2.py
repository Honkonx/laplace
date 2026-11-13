"""Cobertura de `services/gateway_fuentes.py`: ramas de degradación de las fuentes de la cascada.

Todo con `httpx.MockTransport` y `monkeypatch`: sin red, sin claves reales, sin la BD real.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.api.core.config import settings
from backend.api.core.exceptions import BSDAPIError, ExternalSourceError
from backend.api.services import _http_retry, gateway_fuentes
from backend.api.services._http_retry import CuotaApiFootballError
from backend.api.services.circuit_breaker import (
    CircuitBreakerAbiertoError,
    EstadoCircuitBreaker,
    obtener_circuit_breaker,
)
from backend.api.services.fechas_bd import FechaBdInvalida

FECHA = "20261110"


@pytest.fixture(autouse=True)
def _sin_esperas(monkeypatch):
    """Sin limitador real de api-football ni sleeps de reintento; claves de prueba."""

    async def _no_esperar():
        return None

    async def _no_dormir(_s):
        return None

    monkeypatch.setattr(_http_retry, "_esperar_turno_api_football", _no_esperar)
    monkeypatch.setattr(_http_retry.asyncio, "sleep", _no_dormir)
    monkeypatch.setattr(settings, "LIVESCORE6_KEY", "k-ls6", raising=False)
    monkeypatch.setattr(settings, "BSD_API_KEY", "k-bsd", raising=False)
    monkeypatch.setattr(settings, "SPORTS_API_KEY", "k-apif", raising=False)


def _correr(funcion, handler, *args):
    async def _go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as cliente:
            return await funcion(cliente, *args)

    return asyncio.run(_go())


# ─── helpers puros ────────────────────────────────────────────────────────────


def test_fecha_yyyymmdd_valida_y_basura():
    assert gateway_fuentes._yyyymmdd_to_bd("20261110") == "2026-11-10"  # noqa: SLF001
    with pytest.raises(FechaBdInvalida):
        gateway_fuentes._yyyymmdd_to_bd("2026--0-9-")  # noqa: SLF001


def test_timestamp_a_esd_aplica_el_offset_de_chile_tambien_al_dia():
    # 02:30 UTC -> hora 22 (02-4 mod 24) pero la FECHA sigue siendo la UTC: ver defecto en el informe (debería ser 09)
    ts = 1_794_277_800  # 2026-11-10T02:30:00Z
    assert gateway_fuentes._timestamp_to_esd(ts) == "202611092230"  # noqa: SLF001
    assert gateway_fuentes._timestamp_to_iso(ts) == "2026-11-10T02:30:00"  # noqa: SLF001


def test_timestamp_a_iso_invalido_devuelve_cadena_vacia():
    assert gateway_fuentes._timestamp_to_iso("no-es-numero") == ""  # noqa: SLF001
    assert gateway_fuentes._timestamp_to_iso(None) == ""  # noqa: SLF001


@pytest.mark.parametrize(
    "raw, esperado",
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        (123, ""),
        ("https://x.test/a.png", "https://x.test/a.png"),
        ("/img/a.png", "https://lsm-static-prod.livescore.com/img/a.png"),
        ("img/a.png", "https://lsm-static-prod.livescore.com/img/a.png"),
    ],
)
def test_build_img(raw, esperado):
    assert gateway_fuentes._build_img(raw) == esperado  # noqa: SLF001


def test_slug_de_liga():
    assert gateway_fuentes.slug_de_liga("Premier League (ING)") == "premier-league-ing"
    assert gateway_fuentes.slug_de_liga("") == "otras"
    assert len(gateway_fuentes.slug_de_liga("A" * 100)) == 40


# ─── _bd_stages ───────────────────────────────────────────────────────────────


def test_bd_stages_sin_cache_o_vacia_devuelve_none(monkeypatch):
    for data in ({"hit": False}, {"hit": True, "total": 0}):
        monkeypatch.setattr(gateway_fuentes.partidos_repo, "leer_ligas_cache", lambda _db, _f, d=data: d)
        assert gateway_fuentes._bd_stages(None, FECHA) is None  # noqa: SLF001


def test_bd_stages_arma_eventos_y_omite_ligas_sin_partidos(monkeypatch):
    llamadas = []

    def _leer(_db, fecha_bd):
        llamadas.append(fecha_bd)
        return {
            "hit": True,
            "total": 2,
            "ligas": {
                "liga-a": {
                    "nombre": "Liga A",
                    "partidos": [
                        {"match_id": 7, "local": "L", "visitante": "V", "hora_chile": "21:30", "kick_off_utc": "k"},
                        {},
                    ],
                },
                "liga-b": {"partidos": []},
                "liga-c": {"partidos": [{"match_id": 9}]},
            },
        }

    monkeypatch.setattr(gateway_fuentes.partidos_repo, "leer_ligas_cache", _leer)
    stages = gateway_fuentes._bd_stages(None, FECHA)  # noqa: SLF001
    assert llamadas == ["2026-11-10"]
    assert [s["liga_slug"] for s in stages] == ["liga-a", "liga-c"]
    assert stages[0]["Snm"] == "Liga A" and stages[1]["Snm"] == "liga-c"  # sin nombre usa el slug
    ev = stages[0]["Events"]
    assert ev[0]["Esd"] == "202611102130" and ev[0]["Eid"] == "7"
    assert ev[1]["Esd"] == "202611100000" and ev[1]["T1"][0]["Nm"] == "Local" and ev[1]["T2"][0]["Nm"] == "Visit"


def test_bd_stages_si_todas_las_ligas_vacias_devuelve_none(monkeypatch):
    monkeypatch.setattr(
        gateway_fuentes.partidos_repo,
        "leer_ligas_cache",
        lambda _db, _f: {"hit": True, "total": 1, "ligas": {"x": {"partidos": []}}},
    )
    assert gateway_fuentes._bd_stages(None, FECHA) is None  # noqa: SLF001


# ─── LiveScore6 ───────────────────────────────────────────────────────────────


def test_livescore6_sin_clave_lanza(monkeypatch):
    monkeypatch.setattr(settings, "LIVESCORE6_KEY", "", raising=False)
    with pytest.raises(ExternalSourceError):
        _correr(gateway_fuentes._livescore6_stages, lambda _r: httpx.Response(200, json={}), FECHA)  # noqa: SLF001


def test_livescore6_devuelve_stages_y_none_si_no_hay():
    vistos = {}

    def _ok(req):
        vistos["host"] = req.headers.get("x-rapidapi-host")
        vistos["url"] = str(req.url)
        return httpx.Response(200, json={"Stages": [{"Snm": "X", "Events": []}]})

    assert _correr(gateway_fuentes._livescore6_stages, _ok, FECHA) == [{"Snm": "X", "Events": []}]  # noqa: SLF001
    assert vistos["host"] == "livescore6.p.rapidapi.com" and "Date=20261110" in vistos["url"]
    assert _correr(gateway_fuentes._livescore6_stages, lambda _r: httpx.Response(200, json={"Stages": []}), FECHA) is None  # noqa: SLF001


def test_livescore6_http_500_propaga_para_que_la_cascada_siga():
    with pytest.raises(httpx.HTTPStatusError):
        _correr(gateway_fuentes._livescore6_stages, lambda _r: httpx.Response(500, json={}), FECHA)  # noqa: SLF001


def test_livescore6_429_reintenta_una_vez_y_se_recupera():
    n = {"c": 0}

    def _h(_r):
        n["c"] += 1
        if n["c"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return httpx.Response(200, json={"Stages": [{"Snm": "Z", "Events": []}]})

    assert _correr(gateway_fuentes._livescore6_stages, _h, FECHA)[0]["Snm"] == "Z"  # noqa: SLF001
    assert n["c"] == 2


# ─── BSD ──────────────────────────────────────────────────────────────────────


def test_bsd_sin_clave_lanza(monkeypatch):
    monkeypatch.setattr(settings, "BSD_API_KEY", "", raising=False)
    with pytest.raises(BSDAPIError):
        _correr(gateway_fuentes._bsd_stages, lambda _r: httpx.Response(200, json={}), FECHA)  # noqa: SLF001


def test_bsd_breaker_abierto_salta_sin_hacer_request():
    br = obtener_circuit_breaker("bsd")
    for _ in range(br.umbral_fallos):
        br.registrar_fallo()
    assert br.estado == EstadoCircuitBreaker.OPEN
    llamadas = []

    def _h(r):
        llamadas.append(r)
        return httpx.Response(200, json={"results": []})

    with pytest.raises(CircuitBreakerAbiertoError):
        _correr(gateway_fuentes._bsd_stages, _h, FECHA)  # noqa: SLF001
    assert llamadas == []


def test_bsd_fallo_http_registra_fallo_en_el_breaker_y_propaga():
    br = obtener_circuit_breaker("bsd")
    antes = br._fallos_consecutivos  # noqa: SLF001
    with pytest.raises(httpx.HTTPStatusError):
        _correr(gateway_fuentes._bsd_stages, lambda _r: httpx.Response(503, json={}), FECHA)  # noqa: SLF001
    assert br._fallos_consecutivos == antes + 1  # noqa: SLF001


def test_bsd_agrupa_por_liga_y_normaliza_equipos():
    cuerpo = {
        "results": [
            {
                "id": 1,
                "league": {"name": "Liga Uno"},
                "event_date": "2026-11-10 18:00:00+00:00",
                "home_team": {"name": "Casa"},
                "away_team": "Fuera",
            },
            {"id": 2, "competition": {"name": "Copa"}, "date": "2026-11-10T20:00:00", "home_team": None, "away_team": {}},
            {"id": 3, "league": {"name": "Liga Uno"}, "home_team": {"name": "C2"}, "away_team": {"name": "F2"}},
            {"id": 4},
        ]
    }
    vistos = {}

    def _h(r):
        vistos["url"] = str(r.url)
        vistos["auth"] = r.headers.get("authorization")
        return httpx.Response(200, json=cuerpo)

    stages = _correr(gateway_fuentes._bsd_stages, _h, FECHA)  # noqa: SLF001
    assert "date_from=2026-11-10" in vistos["url"] and vistos["auth"] == "Token k-bsd"
    por_liga = {s["Snm"]: s["Events"] for s in stages}
    assert set(por_liga) == {"Liga Uno", "Copa", "Otras"}
    uno = por_liga["Liga Uno"]
    assert uno[0]["T1"][0]["Nm"] == "Casa" and uno[0]["T2"][0]["Nm"] == "Fuera"
    assert uno[0]["kick_off_utc"] == "2026-11-10T18:00:00" and uno[0]["Esd"] == "202611100000"
    assert uno[1]["kick_off_utc"] == ""
    copa = por_liga["Copa"][0]
    assert copa["T1"][0]["Nm"] == "Local" and copa["T2"][0]["Nm"] == "Visit"  # equipos ausentes -> valores por omisión
    assert copa["kick_off_utc"] == "2026-11-10T20:00:00"


def test_bsd_sin_resultados_devuelve_none_y_cierra_el_breaker():
    br = obtener_circuit_breaker("bsd")
    br.registrar_fallo()
    assert _correr(gateway_fuentes._bsd_stages, lambda _r: httpx.Response(200, json={"results": []}), FECHA) is None  # noqa: SLF001
    assert br._fallos_consecutivos == 0  # noqa: SLF001


# ─── api-football ─────────────────────────────────────────────────────────────


def test_apifootball_sin_clave_lanza(monkeypatch):
    monkeypatch.setattr(settings, "SPORTS_API_KEY", "", raising=False)
    with pytest.raises(ExternalSourceError):
        _correr(gateway_fuentes._apifootball_stages, lambda _r: httpx.Response(200, json={}), FECHA)  # noqa: SLF001


def test_apifootball_breaker_abierto_salta_sin_hacer_request():
    br = obtener_circuit_breaker("api-football")
    for _ in range(br.umbral_fallos):
        br.registrar_fallo()
    llamadas = []

    def _h(r):
        llamadas.append(r)
        return httpx.Response(200, json={"response": []})

    with pytest.raises(CircuitBreakerAbiertoError):
        _correr(gateway_fuentes._apifootball_stages, _h, FECHA)  # noqa: SLF001
    assert llamadas == []


def test_apifootball_http_500_registra_fallo_y_propaga():
    br = obtener_circuit_breaker("api-football")
    with pytest.raises(httpx.HTTPStatusError):
        _correr(gateway_fuentes._apifootball_stages, lambda _r: httpx.Response(500, json={}), FECHA)  # noqa: SLF001
    assert br._fallos_consecutivos == 1  # noqa: SLF001


def test_apifootball_200_con_errors_cuenta_como_fallo_del_breaker():
    """Un `errors` dentro de un HTTP 200 (cuota agotada) es fallo de la fuente: no «sin partidos» ni éxito."""
    br = obtener_circuit_breaker("api-football")
    cuerpo = {"errors": {"requests": "You have reached the request limit for the day."}, "response": []}
    for _ in range(br.umbral_fallos):
        with pytest.raises(CuotaApiFootballError):
            _correr(gateway_fuentes._apifootball_stages, lambda _r: httpx.Response(200, json=cuerpo), FECHA)  # noqa: SLF001
    assert br.estado == EstadoCircuitBreaker.OPEN
    with pytest.raises(CircuitBreakerAbiertoError):  # y la siguiente ya ni intenta
        _correr(gateway_fuentes._apifootball_stages, lambda _r: httpx.Response(200, json=cuerpo), FECHA)  # noqa: SLF001


def test_apifootball_sin_fixtures_devuelve_none_y_cierra_breaker():
    br = obtener_circuit_breaker("api-football")
    br.registrar_fallo()
    assert _correr(gateway_fuentes._apifootball_stages, lambda _r: httpx.Response(200, json={"errors": [], "response": []}), FECHA) is None  # noqa: SLF001
    assert br._fallos_consecutivos == 0  # noqa: SLF001


def test_apifootball_agrupa_fixtures_y_usa_timestamp_o_valores_por_omision():
    ts = 1_794_277_800
    cuerpo = {
        "errors": [],
        "response": [
            {"league": {"name": "Serie A"}, "fixture": {"id": 11, "timestamp": ts}, "teams": {"home": {"name": "Roma"}, "away": {"name": "Lazio"}}},
            {"fixture": {"id": 12}},
            {"league": {"name": "Serie A"}, "fixture": {"id": 13, "timestamp": ts}, "teams": {}},
        ],
    }
    vistos = {}

    def _h(r):
        vistos["url"] = str(r.url)
        vistos["key"] = r.headers.get("x-apisports-key")
        return httpx.Response(200, json=cuerpo)

    stages = _correr(gateway_fuentes._apifootball_stages, _h, FECHA)  # noqa: SLF001
    assert "date=2026-11-10" in vistos["url"] and vistos["key"] == "k-apif"
    por_liga = {s["Snm"]: s["Events"] for s in stages}
    assert set(por_liga) == {"Serie A", "Otras"}
    a = por_liga["Serie A"]
    assert a[0]["Esd"] == "202611092230" and a[0]["kick_off_utc"] == "2026-11-10T02:30:00"
    assert a[0]["T1"][0]["Nm"] == "Roma" and a[0]["T2"][0]["Nm"] == "Lazio"
    assert a[1]["T1"][0]["Nm"] == "Local" and a[1]["T2"][0]["Nm"] == "Visit"
    sin_ts = por_liga["Otras"][0]
    assert sin_ts["Esd"] == "202611100000" and sin_ts["kick_off_utc"] == ""


def test_cascada_cae_a_la_siguiente_fuente_cuando_bsd_y_apifootball_fallan(monkeypatch):
    """Comportamiento de la cascada tal como la usa el gateway: cada fuente que lanza se salta y se prueba la siguiente."""
    llamadas = []

    async def _cascada(cliente):
        for nombre, fuente in (("bsd", gateway_fuentes._bsd_stages), ("apif", gateway_fuentes._apifootball_stages)):  # noqa: SLF001
            try:
                llamadas.append(nombre)
                resultado = await fuente(cliente, FECHA)
                if resultado:
                    return nombre, resultado
            except Exception:  # noqa: BLE001 — la cascada real captura Exception genérico
                continue
        return None, None

    def _h(r):
        if "bzzoiro" in str(r.url):
            return httpx.Response(502, json={})
        return httpx.Response(
            200, json={"errors": [], "response": [{"league": {"name": "L"}, "fixture": {"id": 1}, "teams": {}}]}
        )

    async def _go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_h)) as c:
            return await _cascada(c)

    nombre, stages = asyncio.run(_go())
    assert llamadas == ["bsd", "apif"] and nombre == "apif" and stages[0]["Snm"] == "L"
